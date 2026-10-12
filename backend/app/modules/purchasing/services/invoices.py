"""Purchase invoices and returns (ADR-0014).

* Totals are always computed here: gross = qty × unit cost, net = gross − discount,
  VAT on net, landed costs spread over the lines by net value (by quantity when every
  line is free) with the rounding residue on the largest line.
* A draft has no effect. Finalising receives the goods at net + landed cost
  (``post_movement`` with the exact value), posts ``purchase.invoice.finalized`` and
  flips the invoice to final in one unit of work; afterwards it is immutable.
* A return removes the goods at the cost they entered with and reverses the supplier
  debt and VAT; the landed share that is not refunded goes to ``price_difference``.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import DomainError, NotFoundError
from app.core.http import Page
from app.core.numbering import next_number
from app.modules.accounting.models import DetailAccount
from app.modules.accounting.services.chart import check_version
from app.modules.accounting.services.fiscal import open_year_for
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.inventory.models import Item, StockDocument, StockDocumentLine, Unit, Warehouse
from app.modules.inventory.services.stock import COST_PLACES, post_movement
from app.modules.organization.models import Organization
from app.modules.parties.services.core import balances
from app.modules.purchasing.models import (
    PurchaseCharge,
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
)
from app.modules.purchasing.schemas import (
    ChargeOut,
    DueOut,
    InvoiceIn,
    InvoiceLineOut,
    InvoiceOut,
    InvoiceQuery,
    InvoiceSummary,
    PriceHistoryOut,
    ReturnIn,
)
from app.modules.purchasing.services import common, orders
from app.modules.purchasing.services.common import HUNDRED, ZERO, rial

# A unit cost this far from the last purchase is flagged on the draft (likely a typo).
PRICE_WARN = Decimal("0.25")


# --- output -----------------------------------------------------------------


def _returned(s: Session, line_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not line_ids:
        return {}
    rows = s.execute(
        select(PurchaseInvoiceLine.original_line_id, func.sum(PurchaseInvoiceLine.qty))
        .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.invoice_id)
        .where(
            PurchaseInvoice.status == "final",
            PurchaseInvoiceLine.original_line_id.in_(line_ids),
        )
        .group_by(PurchaseInvoiceLine.original_line_id)
    ).all()
    return {k: Decimal(v) for k, v in rows if k is not None}


def invoice_out(s: Session, inv: PurchaseInvoice, warnings: list[str] | None = None) -> InvoiceOut:
    items = {
        i.id: i
        for i in s.scalars(select(Item).where(Item.id.in_({ln.item_id for ln in inv.lines})))
    }
    units = common.names(s, Unit, {ln.unit_id for ln in inv.lines})
    parties = common.names(
        s, DetailAccount, {inv.supplier_id} | {c.payee_id for c in inv.charges if c.payee_id}
    )
    wh = s.get(Warehouse, inv.warehouse_id)
    order = s.get(PurchaseOrder, inv.order_id) if inv.order_id else None
    orig = s.get(PurchaseInvoice, inv.original_invoice_id) if inv.original_invoice_id else None
    returnable = inv.kind == "invoice" and inv.status == "final"
    back = _returned(s, [ln.id for ln in inv.lines]) if returnable else {}
    return InvoiceOut(
        id=inv.id,
        kind=inv.kind,
        status=inv.status,
        number=inv.number,
        branch_id=inv.branch_id,
        warehouse_id=inv.warehouse_id,
        warehouse_name=wh.name if wh else "",
        supplier_id=inv.supplier_id,
        supplier_name=parties.get(inv.supplier_id, ""),
        document_date=inv.document_date,
        supplier_invoice_no=inv.supplier_invoice_no,
        supplier_invoice_date=inv.supplier_invoice_date,
        due_date=inv.due_date,
        order_id=inv.order_id,
        order_number=order.number if order else None,
        original_invoice_id=inv.original_invoice_id,
        original_number=orig.number if orig else None,
        subtotal=inv.subtotal,
        discount_total=inv.discount_total,
        tax_total=inv.tax_total,
        charges_total=inv.charges_total,
        grand_total=inv.grand_total,
        cost_total=inv.cost_total,
        note=inv.note,
        voucher_id=inv.voucher_id,
        stock_document_id=inv.stock_document_id,
        lines=[
            InvoiceLineOut(
                id=ln.id,
                line_no=ln.line_no,
                item_id=ln.item_id,
                item_code=items[ln.item_id].code,
                item_name=items[ln.item_id].name,
                unit_id=ln.unit_id,
                unit_name=units.get(ln.unit_id, ""),
                qty=ln.qty,
                base_qty=ln.base_qty,
                unit_cost=ln.unit_cost,
                gross=ln.gross,
                discount=ln.discount,
                net=ln.net,
                vat_rate=ln.vat_rate,
                tax=ln.tax,
                landed=ln.landed,
                total_cost=ln.total_cost,
                expiry_date=ln.expiry_date,
                order_line_id=ln.order_line_id,
                original_line_id=ln.original_line_id,
                returnable_qty=ln.qty - back.get(ln.id, ZERO) if returnable else None,
            )
            for ln in inv.lines
        ],
        charges=[
            ChargeOut(
                id=c.id,
                line_no=c.line_no,
                description=c.description,
                amount=c.amount,
                payee_id=c.payee_id,
                payee_name=parties.get(c.payee_id or inv.supplier_id, ""),
            )
            for c in inv.charges
        ],
        warnings=warnings or [],
        created_at=inv.created_at,
        finalized_at=inv.finalized_at,
        row_version=version_to_str(inv.row_version),
    )


# --- drafts -----------------------------------------------------------------


def _vat_rate(org: Organization, item: Item, given: Decimal | None) -> Decimal:
    if item.vat_exempt:
        rate = ZERO
    elif given is not None:
        rate = given
    else:
        rate = item.vat_rate if item.vat_rate is not None else org.default_vat_rate
    return rate.quantize(Decimal("0.01"))


def _last_costs(s: Session, item_ids: set[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Last final purchase cost per base unit (before landed costs) of each item."""
    out: dict[uuid.UUID, Decimal] = {}
    for item_id in item_ids:
        row = s.execute(
            select(PurchaseInvoiceLine.net, PurchaseInvoiceLine.base_qty)
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.invoice_id)
            .where(
                PurchaseInvoiceLine.item_id == item_id,
                PurchaseInvoice.kind == "invoice",
                PurchaseInvoice.status == "final",
            )
            .order_by(PurchaseInvoice.document_date.desc(), PurchaseInvoice.finalized_at.desc())
            .limit(1)
        ).first()
        if row is not None and row[1]:
            out[item_id] = row[0] / row[1]
    return out


def _allocate(lines: list[PurchaseInvoiceLine], charges: Decimal) -> None:
    """Spread landed costs by net value; by base quantity when every line is free."""
    weights = [ln.net for ln in lines]
    if not any(weights):
        weights = [ln.base_qty for ln in lines]
    total = sum(weights, ZERO)
    biggest = max(range(len(lines)), key=lambda i: weights[i])
    done = ZERO
    for i, ln in enumerate(lines):
        ln.landed = rial(charges * weights[i] / total) if i != biggest else ZERO
        done += ln.landed
    lines[biggest].landed = charges - done
    for ln in lines:
        ln.total_cost = ln.net + ln.landed


def _apply(s: Session, actor: Actor, inv: PurchaseInvoice, data: InvoiceIn) -> list[str]:
    wh = common.warehouse(s, actor, data.warehouse_id)
    party, _ = common.supplier(s, data.supplier_id)
    org = s.scalars(select(Organization)).one()
    items = common.items(s, {ln.item_id for ln in data.lines})
    order: PurchaseOrder | None = None
    order_lines: dict[uuid.UUID, uuid.UUID] = {}
    if data.order_id:
        order = s.get(PurchaseOrder, data.order_id)
        if order is None or order.branch_id != wh.branch_id:
            raise DomainError("سفارش خرید در این شعبه یافت نشد", code="bad_order")
        if order.status != "approved":
            raise DomainError("فقط سفارش تأییدشده و باز دریافت می‌شود", code="order_not_open")
        if order.supplier_id != data.supplier_id:
            raise DomainError("تأمین‌کننده با سفارش یکی نیست", code="order_supplier")
        order_lines = {ln.id: ln.item_id for ln in order.lines}

    inv.branch_id, inv.warehouse_id, inv.supplier_id = wh.branch_id, wh.id, data.supplier_id
    inv.document_date = data.document_date
    inv.supplier_invoice_no = data.supplier_invoice_no
    inv.supplier_invoice_date = data.supplier_invoice_date
    terms = party.payment_terms_days
    inv.due_date = data.due_date or (
        data.document_date + timedelta(days=terms) if terms is not None else None
    )
    inv.order_id = order.id if order else None
    inv.note = data.note
    if inv.lines or inv.charges:
        inv.lines.clear()
        inv.charges.clear()
        s.flush()

    warnings: list[str] = []
    last = _last_costs(s, set(items))
    for n, ln in enumerate(data.lines, start=1):
        item = items[ln.item_id]
        unit_id = ln.unit_id or item.base_unit_id
        if ln.order_line_id is not None and order_lines.get(ln.order_line_id) != item.id:
            raise DomainError(f"ردیف {n} با ردیف‌های سفارش مطابقت ندارد", code="bad_order_line")
        if item.track_expiry and ln.expiry_date is None:
            raise DomainError(
                f"ردیف {n}: تاریخ انقضای «{item.name}» الزامی است", code="expiry_required"
            )
        bq = common.base_qty(s, item, unit_id, ln.qty)
        gross = rial(ln.qty * ln.unit_cost)
        if ln.discount > gross:
            raise DomainError(f"ردیف {n}: تخفیف از مبلغ ردیف بیشتر است", code="discount_too_high")
        net = gross - ln.discount
        rate = _vat_rate(org, item, ln.vat_rate)
        prev = last.get(item.id)
        if prev and bq and abs(net / bq - prev) > prev * PRICE_WARN:
            warnings.append(
                f"بهای «{item.name}» با آخرین خرید ({rial(prev):f} ریال برای هر واحد پایه) "
                "بیش از ۲۵٪ تفاوت دارد"
            )
        inv.lines.append(
            PurchaseInvoiceLine(
                line_no=n,
                item_id=item.id,
                unit_id=unit_id,
                qty=ln.qty,
                base_qty=bq,
                unit_cost=ln.unit_cost,
                gross=gross,
                discount=ln.discount,
                net=net,
                vat_rate=rate,
                tax=rial(net * rate / HUNDRED),
                landed=ZERO,
                total_cost=net,
                expiry_date=ln.expiry_date,
                order_line_id=ln.order_line_id,
            )
        )
    for n, c in enumerate(data.charges, start=1):
        if c.payee_id is not None and c.payee_id != data.supplier_id:
            common.active_party(s, c.payee_id)
        inv.charges.append(
            PurchaseCharge(
                line_no=n,
                description=c.description,
                amount=c.amount,
                payee_id=None if c.payee_id == data.supplier_id else c.payee_id,
            )
        )
    _totals(inv)
    return warnings


def _totals(inv: PurchaseInvoice) -> None:
    charges = sum((c.amount for c in inv.charges), ZERO)
    _allocate(list(inv.lines), charges)
    inv.subtotal = sum((ln.gross for ln in inv.lines), ZERO)
    inv.discount_total = sum((ln.discount for ln in inv.lines), ZERO)
    inv.tax_total = sum((ln.tax for ln in inv.lines), ZERO)
    inv.charges_total = charges
    inv.cost_total = sum((ln.total_cost for ln in inv.lines), ZERO)
    inv.grand_total = inv.subtotal - inv.discount_total + inv.tax_total + charges


def create(s: Session, actor: Actor, data: InvoiceIn) -> InvoiceOut:
    inv = PurchaseInvoice(
        kind="invoice", status="draft", created_by=actor.user_id, updated_by=actor.user_id
    )
    warnings = _apply(s, actor, inv, data)
    s.add(inv)
    s.flush()
    return invoice_out(s, inv, warnings)


def _get(s: Session, actor: Actor, invoice_id: uuid.UUID, lock: bool = False) -> PurchaseInvoice:
    inv = s.get(PurchaseInvoice, invoice_id, with_for_update=lock)
    if inv is None or not actor.can_access_branch(inv.branch_id):
        raise NotFoundError("فاکتور خرید یافت نشد")
    return inv


def _draft(s: Session, actor: Actor, invoice_id: uuid.UUID, version: str) -> PurchaseInvoice:
    inv = _get(s, actor, invoice_id, lock=True)
    check_version(inv.row_version, version, "این فاکتور")
    if inv.status != "draft":
        raise DomainError(
            "فاکتور قطعی تغییر نمی‌کند؛ برای اصلاح برگشت از خرید ثبت کنید", code="invoice_final"
        )
    return inv


def update(
    s: Session, actor: Actor, invoice_id: uuid.UUID, data: InvoiceIn, version: str
) -> InvoiceOut:
    inv = _draft(s, actor, invoice_id, version)
    warnings = _apply(s, actor, inv, data)
    inv.updated_by = actor.user_id
    s.flush()
    return invoice_out(s, inv, warnings)


def delete(s: Session, actor: Actor, invoice_id: uuid.UUID, version: str) -> None:
    inv = _draft(s, actor, invoice_id, version)
    s.delete(inv)
    s.flush()
    audit.record(
        s,
        "purchasing.draft_deleted",
        user_id=actor.user_id,
        branch_id=inv.branch_id,
        entity_type="purchase_invoice",
        entity_id=inv.id,
    )


def get(s: Session, actor: Actor, invoice_id: uuid.UUID) -> InvoiceOut:
    return invoice_out(s, _get(s, actor, invoice_id))


# --- finalise ---------------------------------------------------------------


def _stock_document(
    s: Session, inv: PurchaseInvoice, doc_type: str, description: str, actor: Actor
) -> StockDocument:
    doc = StockDocument(
        branch_id=inv.branch_id,
        warehouse_id=inv.warehouse_id,
        fiscal_year_id=inv.fiscal_year_id,
        doc_type=doc_type,
        document_date=inv.document_date,
        status="final",
        description=description,
        source_type="purchase_invoice",
        source_id=inv.id,
        finalized_at=utcnow(),
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(doc)
    s.flush()
    return doc


def _stock_line(
    s: Session, doc: StockDocument, n: int, item: Item, ln: PurchaseInvoiceLine
) -> StockDocumentLine:
    sdl = StockDocumentLine(
        document_id=doc.id,
        line_no=n,
        item_id=item.id,
        unit_id=item.base_unit_id,
        qty=ln.base_qty,
        base_qty=ln.base_qty,
        unit_cost=(ln.total_cost / ln.base_qty).quantize(COST_PLACES),
        total_cost=ln.total_cost,
        expiry_date=ln.expiry_date,
    )
    s.add(sdl)
    s.flush()
    return sdl


def finalize(s: Session, actor: Actor, invoice_id: uuid.UUID, version: str) -> InvoiceOut:
    inv = _draft(s, actor, invoice_id, version)
    common.warehouse(s, actor, inv.warehouse_id)
    common.supplier(s, inv.supplier_id)
    for c in inv.charges:
        if c.payee_id is not None:
            common.active_party(s, c.payee_id)
    if inv.supplier_invoice_no and s.scalar(
        select(PurchaseInvoice.id).where(
            PurchaseInvoice.supplier_id == inv.supplier_id,
            PurchaseInvoice.supplier_invoice_no == inv.supplier_invoice_no,
            PurchaseInvoice.kind == "invoice",
            PurchaseInvoice.status == "final",
        )
    ):
        raise DomainError(
            f"فاکتور شماره {inv.supplier_invoice_no} این تأمین‌کننده قبلاً ثبت شده است",
            code="duplicate_supplier_invoice",
        )
    order = s.get(PurchaseOrder, inv.order_id, with_for_update=True) if inv.order_id else None
    if order is not None and order.status != "approved":
        raise DomainError("سفارش این فاکتور دیگر باز نیست", code="order_not_open")
    fy = open_year_for(s, inv.document_date)
    inv.fiscal_year_id = fy.id
    _totals(inv)  # stored values are recomputed, never trusted

    items = {
        i.id: i
        for i in s.scalars(select(Item).where(Item.id.in_({ln.item_id for ln in inv.lines})))
    }
    doc = _stock_document(s, inv, "purchase", "خرید", actor)
    # Lock balances in item order so concurrent documents never deadlock.
    for n, ln in enumerate(sorted(inv.lines, key=lambda x: (str(x.item_id), x.line_no)), 1):
        item = items[ln.item_id]
        sdl = _stock_line(s, doc, n, item, ln)
        post_movement(
            s,
            item_id=item.id,
            warehouse_id=inv.warehouse_id,
            qty=ln.base_qty,
            unit_cost=sdl.unit_cost,
            value=ln.total_cost,
            document=doc,
            line=sdl,
        )
    inv.stock_document_id = doc.id

    supplier_charges = sum((c.amount for c in inv.charges if c.payee_id is None), ZERO)
    net = inv.subtotal - inv.discount_total
    entries = [
        Entry("inventory", debit=inv.cost_total),
        Entry("vat_receivable", debit=inv.tax_total),
        Entry(
            "payable",
            credit=net + inv.tax_total + supplier_charges,
            detail_account_id=inv.supplier_id,
        ),
    ]
    entries += [
        Entry("payable", credit=c.amount, detail_account_id=c.payee_id, description=c.description)
        for c in inv.charges
        if c.payee_id is not None
    ]
    inv.number = next_number(s, "purchase", fy.id, inv.branch_id)
    doc.description = f"خرید شماره {inv.number}"
    supplier = s.get(DetailAccount, inv.supplier_id)
    v = post_event(
        s,
        event_type="purchase.invoice.finalized",
        document_date=inv.document_date,
        branch_id=inv.branch_id,
        entries=entries,
        actor_id=actor.user_id,
        source_id=inv.id,
        description=f"خرید شماره {inv.number} — {supplier.name if supplier else ''}"
        + (f" (فاکتور {inv.supplier_invoice_no})" if inv.supplier_invoice_no else ""),
    )
    inv.voucher_id = v.id
    inv.updated_by = actor.user_id
    s.flush()
    inv.status, inv.finalized_at = "final", utcnow()
    s.flush()
    if order is not None:
        orders.close_if_received(s, order)
    audit.record(
        s,
        "purchasing.invoice_finalized",
        user_id=actor.user_id,
        branch_id=inv.branch_id,
        entity_type="purchase_invoice",
        entity_id=inv.id,
        data={"number": inv.number, "total": str(inv.grand_total)},
    )
    return invoice_out(s, inv)


# --- returns ----------------------------------------------------------------


def _part(total: Decimal, done: Decimal, qty: Decimal, orig_qty: Decimal, rest: Decimal) -> Decimal:
    """Proportional share of a line amount; the last return takes exactly what is left."""
    if qty == rest:
        return total - done
    return rial(total * qty / orig_qty)


def create_return(s: Session, actor: Actor, invoice_id: uuid.UUID, data: ReturnIn) -> InvoiceOut:
    orig = _get(s, actor, invoice_id, lock=True)
    if orig.kind != "invoice" or orig.status != "final":
        raise DomainError("فقط فاکتور خرید قطعی برگشت می‌خورد", code="not_returnable")
    if data.document_date < orig.document_date:
        raise DomainError("تاریخ برگشت پیش از تاریخ خرید است", code="bad_dates")
    common.warehouse(s, actor, orig.warehouse_id)
    fy = open_year_for(s, data.document_date)
    prior = list(
        s.scalars(
            select(PurchaseInvoiceLine)
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.invoice_id)
            .where(
                PurchaseInvoice.original_invoice_id == orig.id, PurchaseInvoice.status == "final"
            )
        )
    )

    def done(line_id: uuid.UUID, attr: str) -> Decimal:
        return sum((getattr(p, attr) for p in prior if p.original_line_id == line_id), ZERO)

    inv = PurchaseInvoice(
        kind="return",
        status="draft",
        branch_id=orig.branch_id,
        warehouse_id=orig.warehouse_id,
        supplier_id=orig.supplier_id,
        fiscal_year_id=fy.id,
        document_date=data.document_date,
        supplier_invoice_no=orig.supplier_invoice_no,
        original_invoice_id=orig.id,
        order_id=orig.order_id,
        note=data.reason,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(inv)
    by_id = {ln.id: ln for ln in orig.lines}
    seen: set[uuid.UUID] = set()
    for n, rl in enumerate(data.lines, start=1):
        o = by_id.get(rl.original_line_id)
        if o is None:
            raise DomainError("ردیف برگشتی متعلق به این فاکتور نیست", code="bad_return_line")
        if o.id in seen:
            raise DomainError("هر ردیف فقط یک بار در برگشت می‌آید", code="duplicate_return_line")
        seen.add(o.id)
        rest = o.qty - done(o.id, "qty")
        if rl.qty > rest:
            raise DomainError(
                f"مقدار برگشتی ردیف {o.line_no} بیش از باقی‌مانده ({rest.normalize():f}) است",
                code="return_qty_exceeded",
            )

        def part(
            attr: str, o: PurchaseInvoiceLine = o, q: Decimal = rl.qty, r: Decimal = rest
        ) -> Decimal:
            return _part(getattr(o, attr), done(o.id, attr), q, o.qty, r)

        inv.lines.append(
            PurchaseInvoiceLine(
                line_no=n,
                item_id=o.item_id,
                unit_id=o.unit_id,
                qty=rl.qty,
                base_qty=o.base_qty - done(o.id, "base_qty")
                if rl.qty == rest
                else (o.base_qty * rl.qty / o.qty).quantize(Decimal("0.001")),
                unit_cost=o.unit_cost,
                gross=part("gross"),
                discount=part("discount"),
                net=part("net"),
                vat_rate=o.vat_rate,
                tax=part("tax"),
                landed=part("landed"),
                total_cost=part("total_cost"),
                expiry_date=o.expiry_date,
                order_line_id=o.order_line_id,
                original_line_id=o.id,
            )
        )
    s.flush()

    items = {
        i.id: i
        for i in s.scalars(select(Item).where(Item.id.in_({ln.item_id for ln in inv.lines})))
    }
    doc = _stock_document(s, inv, "purchase_return", f"برگشت از خرید شماره {orig.number}", actor)
    cost = ZERO
    for n, ln in enumerate(sorted(inv.lines, key=lambda x: (str(x.item_id), x.line_no)), 1):
        item = items[ln.item_id]
        sdl = _stock_line(s, doc, n, item, ln)
        # Out at the cost the goods came in with (never more than the warehouse holds).
        posted = post_movement(
            s,
            item_id=item.id,
            warehouse_id=inv.warehouse_id,
            qty=-ln.base_qty,
            unit_cost=None,
            value=ln.total_cost,
            document=doc,
            line=sdl,
        )
        if -posted.value != ln.total_cost:
            sdl.total_cost = -posted.value
            sdl.unit_cost = (-posted.value / ln.base_qty).quantize(COST_PLACES)
        cost += -posted.value
    inv.stock_document_id = doc.id

    net = sum((ln.net for ln in inv.lines), ZERO)
    inv.subtotal = sum((ln.gross for ln in inv.lines), ZERO)
    inv.discount_total = sum((ln.discount for ln in inv.lines), ZERO)
    inv.tax_total = sum((ln.tax for ln in inv.lines), ZERO)
    inv.charges_total = ZERO
    inv.grand_total = net + inv.tax_total
    inv.cost_total = cost
    diff = net - cost
    inv.number = next_number(s, "purchase_return", fy.id, inv.branch_id)
    v = post_event(
        s,
        event_type="purchase.return.finalized",
        document_date=inv.document_date,
        branch_id=inv.branch_id,
        entries=[
            Entry("payable", debit=inv.grand_total, detail_account_id=inv.supplier_id),
            Entry("vat_receivable", credit=inv.tax_total),
            Entry("inventory", credit=cost),
            Entry(
                "price_difference",
                debit=-diff if diff < 0 else ZERO,
                credit=diff if diff > 0 else ZERO,
            ),
        ],
        actor_id=actor.user_id,
        source_id=inv.id,
        description=f"برگشت از خرید شماره {orig.number} — {data.reason}",
    )
    inv.voucher_id = v.id
    s.flush()
    inv.status, inv.finalized_at = "final", utcnow()
    s.flush()
    audit.record(
        s,
        "purchasing.return_created",
        user_id=actor.user_id,
        branch_id=inv.branch_id,
        entity_type="purchase_invoice",
        entity_id=inv.id,
        data={"original": orig.number, "total": str(inv.grand_total), "reason": data.reason},
    )
    s.refresh(inv)
    return invoice_out(s, inv)


# --- queries ----------------------------------------------------------------


def list_invoices(s: Session, actor: Actor, q: InvoiceQuery) -> Page[InvoiceSummary]:
    stmt = select(PurchaseInvoice)
    if actor.branch_ids is not None:
        stmt = stmt.where(PurchaseInvoice.branch_id.in_(actor.branch_ids))
    if q.kind:
        stmt = stmt.where(PurchaseInvoice.kind == q.kind)
    if q.status:
        stmt = stmt.where(PurchaseInvoice.status == q.status)
    if q.supplier_id:
        stmt = stmt.where(PurchaseInvoice.supplier_id == q.supplier_id)
    if q.date_from:
        stmt = stmt.where(PurchaseInvoice.document_date >= q.date_from)
    if q.date_to:
        stmt = stmt.where(PurchaseInvoice.document_date <= q.date_to)
    if q.q:
        conds = [PurchaseInvoice.supplier_invoice_no == q.q]
        if q.q.isdigit():
            conds.append(PurchaseInvoice.number == int(q.q))
        stmt = stmt.where(or_(*conds))
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(PurchaseInvoice.document_date.desc(), PurchaseInvoice.created_at.desc())
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    sups = common.names(s, DetailAccount, {r.supplier_id for r in rows})
    return Page(
        items=[
            InvoiceSummary(
                id=r.id,
                kind=r.kind,
                status=r.status,
                number=r.number,
                supplier_id=r.supplier_id,
                supplier_name=sups.get(r.supplier_id, ""),
                supplier_invoice_no=r.supplier_invoice_no,
                document_date=r.document_date,
                due_date=r.due_date,
                grand_total=r.grand_total,
            )
            for r in rows
        ],
        total=total,
        page=q.page,
        page_size=q.page_size,
    )


def price_history(s: Session, item_id: uuid.UUID, limit: int = 20) -> list[PriceHistoryOut]:
    rows = s.execute(
        select(PurchaseInvoiceLine, PurchaseInvoice)
        .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.invoice_id)
        .where(
            PurchaseInvoiceLine.item_id == item_id,
            PurchaseInvoice.kind == "invoice",
            PurchaseInvoice.status == "final",
        )
        .order_by(PurchaseInvoice.document_date.desc(), PurchaseInvoice.finalized_at.desc())
        .limit(limit)
    ).all()
    sups = common.names(s, DetailAccount, {inv.supplier_id for _, inv in rows})
    units = common.names(s, Unit, {ln.unit_id for ln, _ in rows})
    return [
        PriceHistoryOut(
            invoice_id=inv.id,
            number=inv.number,
            document_date=inv.document_date,
            supplier_name=sups.get(inv.supplier_id, ""),
            qty=ln.qty,
            unit_name=units.get(ln.unit_id, ""),
            unit_cost=ln.unit_cost,
            base_unit_cost=rial(ln.total_cost / ln.base_qty),
        )
        for ln, inv in rows
    ]


def due_list(s: Session, actor: Actor, until: date, today: date) -> list[DueOut]:
    """Final purchase invoices due by ``until`` that are still (probably) unpaid.

    Payments are not matched to invoices, so the supplier's payable balance is assumed
    to settle the oldest invoices first: walking from the newest invoice back, each one
    is outstanding for whatever part of the balance is still uncovered.
    """
    stmt = select(PurchaseInvoice).where(
        PurchaseInvoice.kind == "invoice",
        PurchaseInvoice.status == "final",
        PurchaseInvoice.due_date.is_not(None),
    )
    if actor.branch_ids is not None:
        stmt = stmt.where(PurchaseInvoice.branch_id.in_(actor.branch_ids))
    invoices = list(
        s.scalars(
            stmt.order_by(PurchaseInvoice.document_date.desc(), PurchaseInvoice.number.desc())
        )
    )
    suppliers = {i.supplier_id for i in invoices}
    owed = {k: -v for k, v in balances(s, list(suppliers)).items()}
    sups = common.names(s, DetailAccount, suppliers)
    left = dict(owed)
    out: list[DueOut] = []
    for inv in invoices:
        remaining = left.get(inv.supplier_id, ZERO)
        if remaining <= 0:
            continue
        # Charges billed by someone else (a carrier) are owed to them, not the supplier.
        own = inv.grand_total - sum((c.amount for c in inv.charges if c.payee_id), ZERO)
        outstanding = min(own, remaining)
        left[inv.supplier_id] = remaining - outstanding
        assert inv.due_date is not None
        if inv.due_date <= until:
            out.append(
                DueOut(
                    supplier_id=inv.supplier_id,
                    supplier_name=sups.get(inv.supplier_id, ""),
                    invoice_id=inv.id,
                    number=inv.number,
                    supplier_invoice_no=inv.supplier_invoice_no,
                    document_date=inv.document_date,
                    due_date=inv.due_date,
                    grand_total=inv.grand_total,
                    outstanding=outstanding,
                    supplier_balance=owed.get(inv.supplier_id, ZERO),
                    overdue_days=max((today - inv.due_date).days, 0),
                )
            )
    out.sort(key=lambda d: (d.due_date, d.supplier_name))
    return out
