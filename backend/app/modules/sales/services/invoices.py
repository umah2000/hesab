"""Checkout, held carts, returns and sales reports (posting-rules.md §2–4, ADR-0013).

A sale is one unit of work: price again on the server, check payments, issue stock,
post the voucher from posting rules, take the gap-free number, then mark final.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from nextcam_core.pricing import ItemRef
from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import Session

from app.core.db import IN_CHUNK, utcnow
from app.core.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from app.core.http import Page
from app.core.numbering import next_number
from app.modules.accounting.models import DetailAccount, PostingRule, Voucher, VoucherLine
from app.modules.accounting.services.fiscal import open_year_for
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.inventory.models import Item, StockDocument, StockDocumentLine, Unit
from app.modules.inventory.services.stock import COST_PLACES, post_movement, tehran_today
from app.modules.organization.models import CashRegister
from app.modules.sales.models import SalesInvoice, SalesInvoiceLine, SalesPayment
from app.modules.sales.schemas import (
    CheckoutIn,
    CustomerOut,
    DailyRegisterRow,
    DailyReportOut,
    HoldIn,
    InvoiceLineOut,
    InvoiceOut,
    InvoiceQuery,
    InvoiceSummaryOut,
    LineRemovalIn,
    MethodTotal,
    PaymentIn,
    PaymentOut,
    ReturnIn,
)
from app.modules.sales.services import approvals, terminal
from app.modules.sales.services.pricing import (
    PricedCart,
    organization,
    price_cart,
    register_and_warehouse,
    rial,
)
from app.modules.sales.services.shifts import require_open_shift

ZERO = Decimal(0)
METHOD_PERMISSION = {
    "cash": "sales.payment.cash",
    "card": "sales.payment.card",
    "credit": "sales.payment.credit",
}
METHOD_LABEL = {"cash": "نقد", "card": "کارت", "credit": "نسیه"}


# --- output -----------------------------------------------------------------


def _returned(s: Session, line_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not line_ids:
        return {}
    rows = s.execute(
        select(SalesInvoiceLine.original_line_id, func.sum(SalesInvoiceLine.qty))
        .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
        .where(
            SalesInvoiceLine.original_line_id.in_(line_ids),
            SalesInvoice.status == "final",
        )
        .group_by(SalesInvoiceLine.original_line_id)
    ).all()
    return {k: Decimal(v) for k, v in rows if k is not None}


def invoice_out(s: Session, inv: SalesInvoice, warnings: list[str] | None = None) -> InvoiceOut:
    reg = s.get(CashRegister, inv.cash_register_id)
    user = s.get(AppUser, inv.created_by) if inv.created_by else None
    customer = s.get(DetailAccount, inv.customer_id) if inv.customer_id else None
    original = s.get(SalesInvoice, inv.original_invoice_id) if inv.original_invoice_id else None
    lines = list(inv.lines)
    item_ids = list({ln.item_id for ln in lines})
    items = (
        {i.id: i for i in s.scalars(select(Item).where(Item.id.in_(item_ids)))} if item_ids else {}
    )
    unit_ids = list({ln.unit_id for ln in lines})
    units = (
        {u.id: u.name for u in s.scalars(select(Unit).where(Unit.id.in_(unit_ids)))}
        if unit_ids
        else {}
    )
    # A sale finalised in this very request cannot have returns yet.
    fresh = inv.kind == "sale" and inv.finalized_at is not None and s.info.get("fresh") == inv.id
    returned = _returned(s, [ln.id for ln in lines]) if inv.kind == "sale" and not fresh else {}
    return InvoiceOut(
        id=inv.id,
        kind=inv.kind,  # type: ignore[arg-type]
        status=inv.status,  # type: ignore[arg-type]
        number=inv.number,
        document_date=inv.document_date,
        branch_id=inv.branch_id,
        cash_register_id=inv.cash_register_id,
        register_name=reg.name if reg else "",
        shift_id=inv.shift_id,
        cashier_name=(user.full_name or user.username) if user else "",
        customer_id=inv.customer_id,
        customer_name=customer.name if customer else None,
        original_invoice_id=inv.original_invoice_id,
        original_number=original.number if original else None,
        subtotal=inv.subtotal,
        discount_total=inv.discount_total,
        tax_total=inv.tax_total,
        grand_total=inv.grand_total,
        cash_tendered=inv.cash_tendered,
        change_due=inv.change_due,
        note=inv.note,
        voucher_id=inv.voucher_id,
        finalized_at=inv.finalized_at,
        created_at=inv.created_at,
        lines=[
            InvoiceLineOut(
                id=ln.id,
                line_no=ln.line_no,
                item_id=ln.item_id,
                item_code=items[ln.item_id].code if ln.item_id in items else "",
                item_name=items[ln.item_id].name if ln.item_id in items else "",
                unit_id=ln.unit_id,
                unit_name=units.get(ln.unit_id, ""),
                qty=ln.qty,
                unit_price=ln.unit_price,
                price_source=ln.price_source,  # type: ignore[arg-type]
                gross=ln.gross,
                promotion_id=ln.promotion_id,
                promotion_name=None,
                promotion_discount=ln.promotion_discount,
                manual_discount=ln.manual_discount,
                vat_exempt=ln.vat_exempt,
                vat_rate=ln.vat_rate,
                tax=ln.tax,
                line_total=ln.line_total,
                stock_qty=None,
                scanned_barcode=ln.scanned_barcode,
                cost_total=ln.cost_total,
                original_line_id=ln.original_line_id,
                returned_qty=returned.get(ln.id, ZERO),
            )
            for ln in lines
        ],
        payments=[
            PaymentOut(
                method=p.method,  # type: ignore[arg-type]
                amount=p.amount,
                card_reference=p.card_reference,
                terminal_transaction_id=p.terminal_transaction_id,
            )
            for p in inv.payments
        ],
        warnings=warnings or [],
    )


# --- shared helpers ---------------------------------------------------------


def _check_payment_methods(actor: Actor, payments: list[PaymentIn]) -> None:
    for p in payments:
        if not actor.has(METHOD_PERMISSION[p.method]):
            raise PermissionDeniedError(f"مجوز دریافت «{METHOD_LABEL[p.method]}» را ندارید")
    if sum(1 for p in payments if p.method == "cash") > 1:
        raise DomainError("فقط یک ردیف نقدی مجاز است", code="duplicate_cash")
    if sum(1 for p in payments if p.method == "credit") > 1:
        raise DomainError("فقط یک ردیف نسیه مجاز است", code="duplicate_credit")


def _customer(s: Session, customer_id: uuid.UUID | None) -> DetailAccount | None:
    if customer_id is None:
        return None
    # Locked so two registers cannot both use the last of a customer's credit.
    c = s.get(DetailAccount, customer_id, with_for_update=True)
    if c is None or c.kind != "person" or not c.is_active:
        raise NotFoundError("مشتری یافت نشد")
    return c


def _receivable_account(s: Session) -> uuid.UUID | None:
    return s.scalar(
        select(PostingRule.account_id).where(
            PostingRule.event_type == "sales.invoice.finalized",
            PostingRule.line_role == "receivable",
        )
    )


def receivable_balances(
    s: Session, customer_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    """Balances of many customers in one grouped query per chunk (a list of customers)."""
    account_id = _receivable_account(s)
    out = dict.fromkeys(customer_ids, ZERO)
    if account_id is None or not out:
        return out
    pending = list(out)
    for i in range(0, len(pending), IN_CHUNK):
        rows = s.execute(
            select(VoucherLine.detail_account_id, func.sum(VoucherLine.debit - VoucherLine.credit))
            .join(Voucher, Voucher.id == VoucherLine.voucher_id)
            .where(
                Voucher.status == "final",
                VoucherLine.account_id == account_id,
                VoucherLine.detail_account_id.in_(pending[i : i + IN_CHUNK]),
            )
            .group_by(VoucherLine.detail_account_id)
        )
        for cid, total in list(rows):
            if cid is not None:
                out[cid] = Decimal(total or 0)
    return out


def receivable_balance(s: Session, customer_id: uuid.UUID) -> Decimal:
    account_id = _receivable_account(s)
    if account_id is None:
        return ZERO
    total = s.scalar(
        select(func.sum(VoucherLine.debit - VoucherLine.credit))
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(
            Voucher.status == "final",
            VoucherLine.account_id == account_id,
            VoucherLine.detail_account_id == customer_id,
        )
    )
    return Decimal(total or 0)


def list_customers(s: Session, q: str | None) -> list[CustomerOut]:
    from app.modules.parties.models import Party

    stmt = (
        select(DetailAccount)
        .outerjoin(Party, Party.id == DetailAccount.id)
        .where(
            DetailAccount.kind == "person",
            DetailAccount.is_active == true(),
            or_(Party.id.is_(None), Party.is_customer == true()),
        )
    )
    if q:
        stmt = stmt.where(DetailAccount.name.contains(q) | DetailAccount.code.contains(q))
    rows = list(s.scalars(stmt.order_by(DetailAccount.name).limit(30)))
    balances = receivable_balances(s, [c.id for c in rows])
    out = []
    for c in rows:
        bal = balances[c.id]
        out.append(
            CustomerOut(
                id=c.id,
                code=c.code,
                name=c.name,
                credit_limit=c.credit_limit,
                credit_unlimited=c.credit_unlimited,
                balance=bal,
                available=c.credit_limit - bal if c.credit_limit is not None else None,
            )
        )
    return out


def _stock_document(
    s: Session,
    inv: SalesInvoice,
    doc_type: str,
    description: str,
    on: date | None = None,
    fiscal_year_id: uuid.UUID | None = None,
) -> StockDocument:
    doc = StockDocument(
        branch_id=inv.branch_id,
        warehouse_id=inv.warehouse_id,
        fiscal_year_id=fiscal_year_id or inv.fiscal_year_id,
        doc_type=doc_type,
        document_date=on or inv.document_date,
        status="final",
        description=description,
        source_type="sales_invoice",
        source_id=inv.id,
        finalized_at=utcnow(),
        created_by=inv.created_by,
        updated_by=inv.created_by,
    )
    s.add(doc)
    s.flush()
    return doc


# --- checkout ---------------------------------------------------------------


@dataclass
class _Tender:
    cash: Decimal = ZERO
    card: Decimal = ZERO
    credit: Decimal = ZERO


def _check_customer_credit(s: Session, customer: DetailAccount, amount: Decimal) -> None:
    if customer.credit_unlimited:
        return
    if customer.credit_limit is None:
        raise DomainError(f"برای «{customer.name}» فروش نسیه تعریف نشده است", code="no_credit")
    balance = receivable_balance(s, customer.id)
    if balance + amount > customer.credit_limit:
        raise DomainError(
            f"سقف اعتبار «{customer.name}» کافی نیست "
            f"(مانده فعلی {balance:f}، سقف {customer.credit_limit:f} ریال)",
            code="credit_limit_exceeded",
        )


def checkout(s: Session, actor: Actor, data: CheckoutIn) -> InvoiceOut:
    reg, wh = register_and_warehouse(s, data.cash_register_id, actor.branch_ids)
    shift = require_open_shift(s, actor, reg.id)
    if s.get(SalesInvoice, data.id) is not None:
        raise ConflictError("این فاکتور قبلاً ثبت شده است", code="invoice_exists")
    org = organization(s)
    today = tehran_today()
    fy = open_year_for(s, today)
    cart = price_cart(s, data, warehouse_id=wh.id, today=today)

    approver: uuid.UUID | None = None
    # Promotions apply on their own. A manual discount needs the discount permission within
    # the cashier limit; without it (the default cashier role) or above the limit, a
    # supervisor approves it on the register.
    if (
        cart.manual_discount_total
        and not actor.has("sales.invoice.discount_over_limit")
        and (not actor.has("sales.invoice.discount") or cart.needs_discount_approval)
    ):
        approver = approvals.consume(s, actor, data.approval_id, "discount_over_limit", reg.id)

    _check_payment_methods(actor, data.payments)
    paid = sum((p.amount for p in data.payments), ZERO)
    if paid != cart.grand_total:
        raise DomainError(
            f"جمع پرداخت‌ها ({paid:f}) با مبلغ فاکتور ({cart.grand_total:f}) برابر نیست",
            code="payment_mismatch",
        )
    tender = _Tender()
    for p in data.payments:
        setattr(tender, p.method, getattr(tender, p.method) + p.amount)
    customer = _customer(s, data.customer_id)
    if tender.credit:
        if customer is None:
            raise DomainError("برای فروش نسیه مشتری را انتخاب کنید", code="customer_required")
        _check_customer_credit(s, customer, tender.credit)
    change: Decimal | None = None
    if data.cash_tendered is not None:
        if data.cash_tendered < tender.cash:
            raise DomainError("وجه دریافتی از مبلغ نقدی کمتر است", code="tendered_too_low")
        change = data.cash_tendered - tender.cash

    inv = SalesInvoice(
        id=data.id,
        branch_id=reg.branch_id,
        cash_register_id=reg.id,
        shift_id=shift.id,
        fiscal_year_id=fy.id,
        warehouse_id=wh.id,
        kind="sale",
        status="draft",
        document_date=today,
        customer_id=customer.id if customer else None,
        subtotal=cart.subtotal,
        discount_total=cart.discount_total,
        tax_total=cart.tax_total,
        grand_total=cart.grand_total,
        cash_tendered=data.cash_tendered,
        change_due=change,
        note=data.note,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(inv)
    lines = _lines_from_cart(inv, cart)
    for i, p in enumerate(data.payments, start=1):
        tx_id = None
        if p.method == "card":
            if p.terminal_transaction_id:
                tx_id = terminal.use_for_payment(
                    s,
                    p.terminal_transaction_id,
                    register_id=reg.id,
                    amount=p.amount,
                    cart_id=data.id,
                ).id
            elif not p.card_reference:
                raise DomainError(
                    "برای پرداخت کارتی شماره پیگیری رسید کارت‌خوان را وارد کنید",
                    code="card_reference_required",
                )
        inv.payments.append(
            SalesPayment(
                seq=i,
                method=p.method,
                amount=p.amount,
                card_reference=p.card_reference if p.method == "card" else None,
                terminal_transaction_id=tx_id,
            )
        )
    s.flush()

    book_sale(
        s,
        inv,
        lines,
        tender,
        fiscal_year_id=fy.id,
        register_name=reg.name,
        allow_negative=org.negative_stock_policy != "deny",
        actor_id=actor.user_id,
        stock_date=today,
    )
    if approver is not None:
        audit.record(
            s,
            "sales.discount_over_limit",
            user_id=actor.user_id,
            branch_id=reg.branch_id,
            entity_type="sales_invoice",
            entity_id=inv.id,
            data={
                "approved_by": str(approver),
                "percent": str(cart.manual_percent),
                "amount": str(cart.manual_discount_total),
            },
        )
    s.info["fresh"] = inv.id
    return invoice_out(s, inv, cart.warnings)


def book_sale(
    s: Session,
    inv: SalesInvoice,
    lines: list[tuple[SalesInvoiceLine, ItemRef]],
    tender: _Tender,
    *,
    fiscal_year_id: uuid.UUID,
    register_name: str,
    allow_negative: bool,
    actor_id: uuid.UUID | None,
    stock_date: date,
    stock_fiscal_year_id: uuid.UUID | None = None,
) -> None:
    """Stock issue, voucher, final number and the flip to final — one transaction.

    Shared by online checkout and offline sales arriving from a register (ADR-0017);
    ``stock_date`` may be later than the sale date (the ledger never goes backwards),
    even in the next fiscal year (``stock_fiscal_year_id``).
    """
    # Stock: one issue per line, locked in item order so registers never deadlock.
    cost = ZERO
    goods = [ln for ln in lines if ln[1].item_type == "goods"]
    if goods:
        doc = _stock_document(
            s,
            inv,
            "sale",
            f"فروش صندوق {register_name}",
            stock_date,
            stock_fiscal_year_id,
        )
        for n, (row, item) in enumerate(sorted(goods, key=lambda x: str(x[1].id)), start=1):
            sdl = StockDocumentLine(
                document_id=doc.id,
                line_no=n,
                item_id=item.id,
                unit_id=item.base_unit_id,
                qty=row.base_qty,
                base_qty=row.base_qty,
            )
            s.add(sdl)
            s.flush()
            posted = post_movement(
                s,
                item_id=item.id,
                warehouse_id=inv.warehouse_id,
                qty=-row.base_qty,
                unit_cost=None,
                document=doc,
                line=sdl,
                allow_negative=allow_negative,
            )
            row.cost_total = sdl.total_cost = -posted.value
            cost += -posted.value
        inv.stock_document_id = doc.id
    inv.cost_total = cost

    revenue = sum((r.revenue for r, _ in lines), ZERO)
    entries = [
        Entry("cash", debit=tender.cash),
        Entry("card", debit=tender.card),
        Entry("receivable", debit=tender.credit, detail_account_id=inv.customer_id),
        Entry("discount", debit=inv.discount_total),
        Entry("revenue", credit=revenue + inv.discount_total),
        Entry("vat_payable", credit=inv.tax_total),
        Entry("cogs", debit=cost),
        Entry("inventory", credit=cost),
    ]
    inv.number = next_number(s, "sales", fiscal_year_id, inv.branch_id)
    v = post_event(
        s,
        event_type="sales.invoice.finalized",
        document_date=inv.document_date,
        branch_id=inv.branch_id,
        entries=entries,
        actor_id=actor_id,
        source_id=inv.id,
        description=f"فروش شماره {inv.number} — {register_name}"
        + (f" (آفلاین، صندوق {inv.device_number})" if inv.device_number else ""),
    )
    inv.voucher_id = v.id
    s.flush()  # line costs are written while the invoice is still a draft (DB guard)
    inv.status, inv.finalized_at = "final", utcnow()
    s.flush()


def _lines_from_cart(inv: SalesInvoice, cart: PricedCart) -> list[tuple[SalesInvoiceLine, ItemRef]]:
    out = []
    for ln in cart.lines:
        row = SalesInvoiceLine(
            line_no=ln.line_no,
            item_id=ln.item.id,
            unit_id=ln.unit_id,
            qty=ln.qty,
            base_qty=ln.base_qty,
            unit_price=ln.unit_price,
            price_source=ln.price_source,
            gross=ln.gross,
            promotion_id=ln.promotion.id if ln.promotion else None,
            promotion_discount=ln.promotion_discount,
            manual_discount=ln.manual_discount,
            vat_exempt=ln.vat_exempt,
            vat_rate=ln.vat_rate,
            tax=ln.tax,
            revenue=ln.revenue,
            line_total=ln.line_total,
            scanned_barcode=ln.scanned_barcode,
        )
        inv.lines.append(row)
        out.append((row, ln.item))
    return out


# --- held carts -------------------------------------------------------------


def hold(s: Session, actor: Actor, data: HoldIn) -> InvoiceOut:
    reg, wh = register_and_warehouse(s, data.cash_register_id, actor.branch_ids)
    shift = require_open_shift(s, actor, reg.id)
    cart = price_cart(s, data, warehouse_id=wh.id, today=tehran_today())
    inv = SalesInvoice(
        branch_id=reg.branch_id,
        cash_register_id=reg.id,
        shift_id=shift.id,
        warehouse_id=wh.id,
        kind="sale",
        status="held",
        document_date=tehran_today(),
        customer_id=data.customer_id,
        subtotal=cart.subtotal,
        discount_total=cart.discount_total,
        tax_total=cart.tax_total,
        grand_total=cart.grand_total,
        note=data.note,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(inv)
    _lines_from_cart(inv, cart)
    s.flush()
    s.refresh(inv)
    return invoice_out(s, inv)


def list_held(s: Session, actor: Actor, register_id: uuid.UUID) -> list[InvoiceSummaryOut]:
    reg, _ = register_and_warehouse(s, register_id, actor.branch_ids)
    rows = list(
        s.scalars(
            select(SalesInvoice)
            .where(SalesInvoice.branch_id == reg.branch_id, SalesInvoice.status == "held")
            .order_by(SalesInvoice.created_at)
        )
    )
    return [_summary(s, inv) for inv in rows]


def recall(s: Session, actor: Actor, invoice_id: uuid.UUID) -> InvoiceOut:
    inv = s.get(SalesInvoice, invoice_id, with_for_update=True)
    if inv is None or not actor.can_access_branch(inv.branch_id):
        raise NotFoundError("فاکتور یافت نشد")
    if inv.status != "held":
        raise ConflictError("این فاکتور قبلاً بازیابی شده است", code="not_held")
    inv.status, inv.updated_by, inv.updated_at = "recalled", actor.user_id, utcnow()
    s.flush()
    s.refresh(inv)
    return invoice_out(s, inv)


# --- line removal (audit trail of scanned-then-removed goods) ---------------


def record_line_removal(s: Session, actor: Actor, data: LineRemovalIn) -> dict[str, str]:
    reg, _ = register_and_warehouse(s, data.cash_register_id, actor.branch_ids)
    require_open_shift(s, actor, reg.id)
    approver: uuid.UUID | None = None
    if not actor.has("sales.invoice.line_delete_after_scan"):
        approver = approvals.consume(s, actor, data.approval_id, "line_delete", reg.id)
    item = s.get(Item, data.item_id)
    audit.record(
        s,
        "sales.line_removed",
        user_id=actor.user_id,
        branch_id=reg.branch_id,
        entity_type="item",
        entity_id=data.item_id,
        data={
            "register": reg.code,
            "item": item.code if item else None,
            "qty": str(data.qty),
            "line_total": str(data.line_total),
            "approved_by": str(approver) if approver else None,
        },
    )
    return {"status": "recorded"}


# --- returns ----------------------------------------------------------------


def _part(
    total: Decimal, done: Decimal, qty: Decimal, orig_qty: Decimal, remaining: Decimal
) -> Decimal:
    """Proportional share of a line amount; the last return takes exactly what is left."""
    if qty == remaining:
        return total - done
    return rial(total * qty / orig_qty)


def create_return(s: Session, actor: Actor, invoice_id: uuid.UUID, data: ReturnIn) -> InvoiceOut:
    orig = s.get(SalesInvoice, invoice_id, with_for_update=True)
    if orig is None or not actor.can_access_branch(orig.branch_id):
        raise NotFoundError("فاکتور یافت نشد")
    if orig.kind != "sale" or orig.status != "final":
        raise DomainError("فقط فاکتور فروش قطعی برگشت می‌خورد", code="not_returnable")
    reg, wh = register_and_warehouse(s, data.cash_register_id, actor.branch_ids)
    if reg.branch_id != orig.branch_id:
        raise DomainError("برگشت فقط در شعبه فروش ممکن است", code="other_branch")
    shift = require_open_shift(s, actor, reg.id)
    today = tehran_today()
    fy = open_year_for(s, today)
    orig_lines = {ln.id: ln for ln in orig.lines}
    prior = list(
        s.scalars(
            select(SalesInvoiceLine)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .where(SalesInvoice.original_invoice_id == orig.id, SalesInvoice.status == "final")
        )
    )

    def done(line_id: uuid.UUID, attr: str) -> Decimal:
        return sum((getattr(p, attr) or ZERO for p in prior if p.original_line_id == line_id), ZERO)

    inv = SalesInvoice(
        branch_id=reg.branch_id,
        cash_register_id=reg.id,
        shift_id=shift.id,
        fiscal_year_id=fy.id,
        warehouse_id=wh.id,
        kind="return",
        status="draft",
        document_date=today,
        customer_id=orig.customer_id,
        original_invoice_id=orig.id,
        note=data.reason,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(inv)
    seen: set[uuid.UUID] = set()
    rows: list[tuple[SalesInvoiceLine, SalesInvoiceLine]] = []
    for n, rl in enumerate(data.lines, start=1):
        o = orig_lines.get(rl.original_line_id)
        if o is None:
            raise DomainError("ردیف برگشتی متعلق به این فاکتور نیست", code="bad_return_line")
        if o.id in seen:
            raise DomainError("هر ردیف فقط یک بار در برگشت می‌آید", code="duplicate_return_line")
        seen.add(o.id)
        remaining = o.qty - done(o.id, "qty")
        if rl.qty > remaining:
            raise DomainError(
                f"مقدار برگشتی ردیف {o.line_no} بیش از باقی‌مانده ({remaining.normalize():f}) است",
                code="return_qty_exceeded",
            )

        def part(
            attr: str, o: SalesInvoiceLine = o, qty: Decimal = rl.qty, rem: Decimal = remaining
        ) -> Decimal:
            return _part(getattr(o, attr) or ZERO, done(o.id, attr), qty, o.qty, rem)

        row = SalesInvoiceLine(
            line_no=n,
            item_id=o.item_id,
            unit_id=o.unit_id,
            qty=rl.qty,
            base_qty=(o.base_qty * rl.qty / o.qty).quantize(Decimal("0.001"))
            if rl.qty != remaining
            else o.base_qty - done(o.id, "base_qty"),
            unit_price=o.unit_price,
            price_source=o.price_source,
            gross=part("gross"),
            promotion_id=o.promotion_id,
            promotion_discount=part("promotion_discount"),
            manual_discount=part("manual_discount"),
            vat_exempt=o.vat_exempt,
            vat_rate=o.vat_rate,
            tax=part("tax"),
            revenue=part("revenue"),
            line_total=part("line_total"),
            cost_total=part("cost_total") if o.cost_total is not None else None,
            original_line_id=o.id,
        )
        inv.lines.append(row)
        rows.append((row, o))

    inv.subtotal = sum((r.gross for r, _ in rows), ZERO)
    inv.discount_total = sum((r.promotion_discount + r.manual_discount for r, _ in rows), ZERO)
    inv.tax_total = sum((r.tax for r, _ in rows), ZERO)
    inv.grand_total = sum((r.line_total for r, _ in rows), ZERO)

    if len(data.refunds) == 1 and data.refunds[0].amount is None:
        data.refunds[0].amount = inv.grand_total
    if any(p.amount is None for p in data.refunds):
        raise DomainError("مبلغ هر روش استرداد را وارد کنید", code="refund_amount_required")
    tender = _Tender()
    for p in data.refunds:
        if p.method == "card" and not p.card_reference:
            raise DomainError(
                "شماره پیگیری استرداد کارت را وارد کنید", code="card_reference_required"
            )
        if p.method == "credit" and orig.customer_id is None:
            raise DomainError(
                "فاکتور اصلی مشتری ندارد؛ استرداد نسیه ممکن نیست", code="customer_required"
            )
        setattr(tender, p.method, getattr(tender, p.method) + (p.amount or ZERO))
    refunded = tender.cash + tender.card + tender.credit
    if refunded != inv.grand_total:
        raise DomainError(
            f"جمع استرداد ({refunded:f}) با مبلغ برگشت ({inv.grand_total:f}) برابر نیست",
            code="payment_mismatch",
        )
    for i, p in enumerate(data.refunds, start=1):
        inv.payments.append(
            SalesPayment(
                seq=i,
                method=p.method,
                amount=p.amount or ZERO,
                card_reference=p.card_reference if p.method == "card" else None,
            )
        )
    s.flush()

    cost = ZERO
    items = {
        i.id: i for i in s.scalars(select(Item).where(Item.id.in_([r.item_id for r, _ in rows])))
    }
    goods = [(r, o) for r, o in rows if items[r.item_id].item_type == "goods"]
    if goods:
        doc = _stock_document(s, inv, "sale_return", f"برگشت از فروش شماره {orig.number}")
        for n, (row, _o) in enumerate(sorted(goods, key=lambda x: str(x[0].item_id)), start=1):
            value = row.cost_total or ZERO
            sdl = StockDocumentLine(
                document_id=doc.id,
                line_no=n,
                item_id=row.item_id,
                unit_id=items[row.item_id].base_unit_id,
                qty=row.base_qty,
                base_qty=row.base_qty,
                unit_cost=(value / row.base_qty).quantize(COST_PLACES),
                total_cost=value,
            )
            s.add(sdl)
            s.flush()
            # Goods come back at the cost recorded on the original sale (posting-rules.md §2).
            post_movement(
                s,
                item_id=row.item_id,
                warehouse_id=wh.id,
                qty=row.base_qty,
                unit_cost=sdl.unit_cost,
                value=value,
                document=doc,
                line=sdl,
            )
            cost += value
        inv.stock_document_id = doc.id
    inv.cost_total = cost

    inv.number = next_number(s, "sales_return", fy.id, reg.branch_id)
    v = post_event(
        s,
        event_type="sales.return.finalized",
        document_date=today,
        branch_id=reg.branch_id,
        entries=[
            Entry("sales_return", debit=sum((r.revenue for r, _ in rows), ZERO)),
            Entry("vat_payable", debit=inv.tax_total),
            Entry("cash", credit=tender.cash),
            Entry("card", credit=tender.card),
            Entry("receivable", credit=tender.credit, detail_account_id=orig.customer_id),
            Entry("inventory", debit=cost),
            Entry("cogs", credit=cost),
        ],
        actor_id=actor.user_id,
        source_id=inv.id,
        description=f"برگشت از فروش شماره {orig.number} — {data.reason}",
    )
    inv.voucher_id = v.id
    s.flush()
    inv.status, inv.finalized_at = "final", utcnow()
    s.flush()
    audit.record(
        s,
        "sales.return_created",
        user_id=actor.user_id,
        branch_id=reg.branch_id,
        entity_type="sales_invoice",
        entity_id=inv.id,
        data={"original": orig.number, "total": str(inv.grand_total), "reason": data.reason},
    )
    s.refresh(inv)
    return invoice_out(s, inv)


# --- queries ----------------------------------------------------------------


@dataclass
class _Names:
    registers: dict[uuid.UUID, str]
    users: dict[uuid.UUID, str]
    customers: dict[uuid.UUID, str]


def _names(s: Session, invoices: list[SalesInvoice]) -> _Names:
    """Display names for a page of invoices in three queries (not three per row)."""
    regs = {i.cash_register_id for i in invoices}
    users = {i.created_by for i in invoices if i.created_by}
    custs = {i.customer_id for i in invoices if i.customer_id}
    return _Names(
        registers=dict(
            s.execute(
                select(CashRegister.id, CashRegister.name).where(CashRegister.id.in_(regs))
            ).all()
        )
        if regs
        else {},
        users={
            uid: full or username
            for uid, full, username in s.execute(
                select(AppUser.id, AppUser.full_name, AppUser.username).where(AppUser.id.in_(users))
            )
        }
        if users
        else {},
        customers=dict(
            s.execute(
                select(DetailAccount.id, DetailAccount.name).where(DetailAccount.id.in_(custs))
            ).all()
        )
        if custs
        else {},
    )


def _summary(
    s: Session, inv: SalesInvoice, line_count: int | None = None, names: _Names | None = None
) -> InvoiceSummaryOut:
    n = names or _names(s, [inv])
    return InvoiceSummaryOut(
        id=inv.id,
        kind=inv.kind,  # type: ignore[arg-type]
        status=inv.status,  # type: ignore[arg-type]
        number=inv.number,
        document_date=inv.document_date,
        register_name=n.registers.get(inv.cash_register_id, ""),
        cashier_name=n.users.get(inv.created_by, "") if inv.created_by else "",
        customer_name=n.customers.get(inv.customer_id) if inv.customer_id else None,
        grand_total=inv.grand_total,
        line_count=len(inv.lines) if line_count is None else line_count,
        note=inv.note,
        created_at=inv.created_at,
    )


def get_invoice(s: Session, actor: Actor, invoice_id: uuid.UUID) -> InvoiceOut:
    inv = s.get(SalesInvoice, invoice_id)
    if inv is None or not actor.can_access_branch(inv.branch_id) or not _may_see(actor, inv):
        raise NotFoundError("فاکتور یافت نشد")
    return invoice_out(s, inv)


def _may_see(actor: Actor, inv: SalesInvoice) -> bool:
    if actor.has("sales.report.view") or actor.has("sales.return.create"):
        return True
    return inv.created_by == actor.user_id


def list_invoices(s: Session, actor: Actor, q: InvoiceQuery) -> Page[InvoiceSummaryOut]:
    stmt = select(SalesInvoice).where(SalesInvoice.status.in_(("final", "held")))
    if q.kind:
        stmt = stmt.where(SalesInvoice.kind == q.kind)
    if q.status:
        stmt = stmt.where(SalesInvoice.status == q.status)
    if q.branch_id:
        stmt = stmt.where(SalesInvoice.branch_id == q.branch_id)
    if actor.branch_ids is not None:
        stmt = stmt.where(SalesInvoice.branch_id.in_(actor.branch_ids))
    if q.cash_register_id:
        stmt = stmt.where(SalesInvoice.cash_register_id == q.cash_register_id)
    if q.shift_id:
        stmt = stmt.where(SalesInvoice.shift_id == q.shift_id)
    if q.date_from:
        stmt = stmt.where(SalesInvoice.document_date >= q.date_from)
    if q.date_to:
        stmt = stmt.where(SalesInvoice.document_date <= q.date_to)
    if q.number is not None:
        stmt = stmt.where(SalesInvoice.number == q.number)
    if not (actor.has("sales.report.view") or actor.has("sales.return.create")):
        stmt = stmt.where(SalesInvoice.created_by == actor.user_id)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    # Count lines in the same query: loading every invoice's lines made a page of 30 cost
    # 30 extra round trips (found by the phase 10 volume test).
    n_lines = (
        select(func.count())
        .where(SalesInvoiceLine.invoice_id == SalesInvoice.id)
        .correlate(SalesInvoice)
        .scalar_subquery()
    )
    rows = list(
        s.execute(
            stmt.add_columns(n_lines)
            .order_by(SalesInvoice.created_at.desc())
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    names = _names(s, [inv for inv, _ in rows])
    return Page(
        items=[_summary(s, inv, n, names) for inv, n in rows],
        total=int(total),
        page=q.page,
        page_size=q.page_size,
    )


def daily_report(
    s: Session, actor: Actor, day: date, branch_id: uuid.UUID | None
) -> DailyReportOut:
    base = select(SalesInvoice).where(
        SalesInvoice.status == "final", SalesInvoice.document_date == day
    )
    if branch_id:
        base = base.where(SalesInvoice.branch_id == branch_id)
    if actor.branch_ids is not None:
        base = base.where(SalesInvoice.branch_id.in_(actor.branch_ids))
    inv = base.subquery()
    agg = {
        k: (int(c), Decimal(g or 0), Decimal(d or 0), Decimal(t or 0), Decimal(co or 0))
        for k, c, g, d, t, co in s.execute(
            select(
                inv.c.kind,
                func.count(),
                func.sum(inv.c.grand_total),
                func.sum(inv.c.discount_total),
                func.sum(inv.c.tax_total),
                func.sum(inv.c.cost_total),
            ).group_by(inv.c.kind)
        ).all()
    }
    zero = (0, ZERO, ZERO, ZERO, ZERO)
    sale, ret = agg.get("sale", zero), agg.get("return", zero)
    methods = {
        (k, m): Decimal(v or 0)
        for k, m, v in s.execute(
            select(inv.c.kind, SalesPayment.method, func.sum(SalesPayment.amount))
            .join(SalesPayment, SalesPayment.invoice_id == inv.c.id)
            .group_by(inv.c.kind, SalesPayment.method)
        ).all()
    }
    regs = s.execute(
        select(
            inv.c.cash_register_id, inv.c.kind, func.count(), func.sum(inv.c.grand_total)
        ).group_by(inv.c.cash_register_id, inv.c.kind)
    ).all()
    per: dict[uuid.UUID, DailyRegisterRow] = {}
    for rid, kind, c, g in regs:
        reg = s.get(CashRegister, rid)
        row = per.setdefault(
            rid,
            DailyRegisterRow(
                cash_register_id=rid,
                register_name=reg.name if reg else "",
                sale_count=0,
                sales_total=ZERO,
                returns_total=ZERO,
            ),
        )
        if kind == "sale":
            row.sale_count, row.sales_total = int(c), Decimal(g or 0)
        else:
            row.returns_total = Decimal(g or 0)
    net_ex_tax = (sale[1] - sale[3]) - (ret[1] - ret[3])
    cost = sale[4] - ret[4]
    return DailyReportOut(
        date=day,
        branch_id=branch_id,
        sale_count=sale[0],
        return_count=ret[0],
        sales_total=sale[1],
        returns_total=ret[1],
        net_total=sale[1] - ret[1],
        discount_total=sale[2] - ret[2],
        tax_total=sale[3] - ret[3],
        cost_total=cost,
        gross_profit=net_ex_tax - cost,
        by_method=[
            MethodTotal(
                method=m,
                sales=methods.get(("sale", m), ZERO),
                refunds=methods.get(("return", m), ZERO),
            )
            for m in ("cash", "card", "credit")
        ],
        by_register=sorted(per.values(), key=lambda r: r.register_name),
    )
