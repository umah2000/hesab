"""Sales orders from visitors: received, priced, approved, invoiced, delivered (ADR-0018).

* The phone never decides a price: every order is priced here with the shared core
  (``sales.services.pricing``) when it arrives. The phone's own estimate is only kept
  to show the visitor that the price changed.
* An order does not touch stock or the books. Invoicing turns an approved order into an
  ordinary credit sales invoice (``book_sale``): stock issue, voucher, gap-free number.
* Credit is checked on approval and again on invoicing, counting approved orders that
  are not invoiced yet.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from app.core.http import Page
from app.core.numbering import next_number
from app.modules.accounting.models import DetailAccount
from app.modules.accounting.services.chart import check_version
from app.modules.accounting.services.fiscal import open_year_for
from app.modules.audit import service as audit
from app.modules.distribution.models import SalesOrder, SalesOrderLine, Visit, Visitor
from app.modules.distribution.schemas import (
    DecisionIn,
    InvoiceOrderIn,
    OrderIn,
    OrderLineOut,
    OrderOut,
    OrderQuery,
    OrderSummaryOut,
    QuoteIn,
    QuoteOut,
    RejectIn,
    VisitIn,
    VisitOut,
)
from app.modules.distribution.services import visitors
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.inventory.models import Item, Unit, Warehouse
from app.modules.inventory.services.stock import tehran_today
from app.modules.organization.models import CashRegister
from app.modules.sales.models import Promotion, SalesInvoice, SalesInvoiceLine, SalesPayment
from app.modules.sales.services import pricing
from app.modules.sales.services.invoices import _Tender, book_sale, receivable_balance

ZERO = Decimal(0)
TEHRAN = ZoneInfo("Asia/Tehran")
OPEN = ("submitted", "approved")


# --- pricing -----------------------------------------------------------------------------


def branch_warehouse(s: Session, branch_id: uuid.UUID) -> uuid.UUID:
    wh = s.scalar(
        select(Warehouse.id)
        .where(Warehouse.branch_id == branch_id, Warehouse.is_active == true())
        .order_by(Warehouse.code)
    )
    if wh is None:
        raise DomainError("برای این شعبه انباری تعریف نشده است", code="no_warehouse")
    return wh


def _price(s: Session, branch_id: uuid.UUID, data: QuoteIn) -> tuple[pricing.PricedCart, uuid.UUID]:
    wh = branch_warehouse(s, branch_id)
    lines = [
        pricing.LineIn(item_id=ln.item_id, qty=ln.qty, unit_id=ln.unit_id) for ln in data.lines
    ]
    return pricing.price_lines(s, lines, warehouse_id=wh, today=tehran_today()), wh


def _line_out(ln: pricing.PricedLine) -> OrderLineOut:
    return OrderLineOut(
        line_no=ln.line_no,
        item_id=ln.item.id,
        item_code=ln.item.code,
        item_name=ln.item.name,
        unit_id=ln.unit_id,
        unit_name=ln.unit_name,
        qty=ln.qty,
        unit_price=ln.unit_price,
        gross=ln.gross,
        promotion_name=ln.promotion.name if ln.promotion else None,
        promotion_discount=ln.promotion_discount,
        vat_rate=ln.vat_rate,
        tax=ln.tax,
        line_total=ln.line_total,
        stock_qty=ln.stock_qty,
    )


def credit_of(
    s: Session, customer_id: uuid.UUID, *, exclude: uuid.UUID | None = None
) -> tuple[Decimal | None, Decimal, bool]:
    """(credit limit, what is owed + approved orders not invoiced yet, unlimited)."""
    acc = s.get(DetailAccount, customer_id)
    if acc is None:
        raise NotFoundError("مشتری یافت نشد")
    q = select(func.coalesce(func.sum(SalesOrder.grand_total), 0)).where(
        SalesOrder.customer_id == customer_id, SalesOrder.status == "approved"
    )
    if exclude is not None:
        q = q.where(SalesOrder.id != exclude)
    pending = Decimal(s.scalar(q) or 0)
    return acc.credit_limit, receivable_balance(s, customer_id) + pending, acc.credit_unlimited


def _rials(d: Decimal) -> str:
    """A message amount the way people read it: ۱۲٬۵۰۰٬۰۰۰ ریال."""
    grouped = f"{int(d.to_integral_value()):,}".replace(",", "٬")
    return grouped.translate(str.maketrans("0123456789-", "۰۱۲۳۴۵۶۷۸۹−")) + " ریال"


def _check_credit(s: Session, order: SalesOrder) -> None:
    acc = s.get(DetailAccount, order.customer_id, with_for_update=True)
    if acc is None:
        raise NotFoundError("مشتری یافت نشد")
    limit, used, unlimited = credit_of(s, order.customer_id, exclude=order.id)
    if unlimited:
        return
    if limit is None:
        raise DomainError(f"برای «{acc.name}» فروش نسیه تعریف نشده است", code="no_credit")
    if used + order.grand_total > limit:
        raise DomainError(
            f"سقف اعتبار «{acc.name}» کافی نیست: بدهی و سفارش‌های تأییدشده {_rials(used)}، "
            f"این سفارش {_rials(order.grand_total)}، سقف {_rials(limit)}",
            code="credit_limit_exceeded",
        )


def quote(s: Session, actor: Actor, data: QuoteIn) -> QuoteOut:
    v = visitors.of_actor(s, actor)
    if not visitors.is_assigned(s, v.id, data.customer_id):
        raise PermissionDeniedError("این مشتری به شما تخصیص داده نشده است", code="not_assigned")
    cart, _ = _price(s, v.branch_id, data)
    limit, used, unlimited = credit_of(s, data.customer_id)
    return QuoteOut(
        lines=[_line_out(ln) for ln in cart.lines],
        subtotal=cart.subtotal,
        discount_total=cart.discount_total,
        tax_total=cart.tax_total,
        grand_total=cart.grand_total,
        warnings=cart.warnings,
        credit_limit=limit,
        credit_unlimited=unlimited,
        balance=used,
        available_after=limit - used - cart.grand_total if limit is not None else None,
    )


# --- output --------------------------------------------------------------------------------


def _name(s: Session, user_id: uuid.UUID | None) -> str | None:
    u = s.get(AppUser, user_id) if user_id else None
    return (u.full_name or u.username) if u else None


def order_out(s: Session, o: SalesOrder, warnings: list[str] | None = None) -> OrderOut:
    v = s.get(Visitor, o.visitor_id)
    customer = s.get(DetailAccount, o.customer_id)
    inv = s.get(SalesInvoice, o.invoice_id) if o.invoice_id else None
    lines = list(o.lines)
    items = {
        i.id: i
        for i in s.scalars(
            select(Item).where(Item.id.in_({ln.item_id for ln in lines} or {uuid.UUID(int=0)}))
        )
    }
    units = {u.id: u.name for u in s.scalars(select(Unit))}
    promos = {
        p.id: p.name
        for p in s.scalars(
            select(Promotion).where(
                Promotion.id.in_(
                    {ln.promotion_id for ln in lines if ln.promotion_id} or {uuid.UUID(int=0)}
                )
            )
        )
    }
    return OrderOut(
        id=o.id,
        number=o.number,
        status=o.status,  # type: ignore[arg-type]
        branch_id=o.branch_id,
        visitor_id=o.visitor_id,
        visitor_name=(_name(s, v.user_id) or "") if v else "",
        customer_id=o.customer_id,
        customer_name=customer.name if customer else "",
        ordered_at=o.ordered_at,
        received_at=o.received_at,
        subtotal=o.subtotal,
        discount_total=o.discount_total,
        tax_total=o.tax_total,
        grand_total=o.grand_total,
        client_total=o.client_total,
        price_changed=o.client_total is not None and o.client_total != o.grand_total,
        note=o.note,
        decided_by_name=_name(s, o.decided_by),
        decided_at=o.decided_at,
        decision_note=o.decision_note,
        invoice_id=o.invoice_id,
        invoice_number=inv.number if inv else None,
        delivered_at=o.delivered_at,
        lines=[
            OrderLineOut(
                line_no=ln.line_no,
                item_id=ln.item_id,
                item_code=items[ln.item_id].code if ln.item_id in items else "",
                item_name=items[ln.item_id].name if ln.item_id in items else "",
                unit_id=ln.unit_id,
                unit_name=units.get(ln.unit_id, ""),
                qty=ln.qty,
                unit_price=ln.unit_price,
                gross=ln.gross,
                promotion_name=promos.get(ln.promotion_id) if ln.promotion_id else None,
                promotion_discount=ln.promotion_discount,
                vat_rate=ln.vat_rate,
                tax=ln.tax,
                line_total=ln.line_total,
            )
            for ln in lines
        ],
        warnings=warnings or [],
        row_version=version_to_str(o.row_version),
    )


def _summary(s: Session, o: SalesOrder) -> OrderSummaryOut:
    v = s.get(Visitor, o.visitor_id)
    customer = s.get(DetailAccount, o.customer_id)
    inv = s.get(SalesInvoice, o.invoice_id) if o.invoice_id else None
    return OrderSummaryOut(
        id=o.id,
        number=o.number,
        status=o.status,  # type: ignore[arg-type]
        visitor_name=(_name(s, v.user_id) or "") if v else "",
        customer_name=customer.name if customer else "",
        ordered_at=o.ordered_at,
        received_at=o.received_at,
        grand_total=o.grand_total,
        price_changed=o.client_total is not None and o.client_total != o.grand_total,
        invoice_number=inv.number if inv else None,
    )


# --- from the phone -----------------------------------------------------------------------


def submit(s: Session, actor: Actor, data: OrderIn) -> tuple[OrderOut, bool]:
    """Receive an order; (order, created). A resend of the same id returns it unchanged."""
    v = visitors.of_actor(s, actor)
    found = s.get(SalesOrder, data.id)
    if found is not None:
        if found.visitor_id != v.id:
            raise ConflictError("این شناسه سفارش قبلاً استفاده شده است", code="order_exists")
        return order_out(s, found), False
    if not visitors.is_assigned(s, v.id, data.customer_id):
        raise PermissionDeniedError("این مشتری به شما تخصیص داده نشده است", code="not_assigned")
    cart, wh = _price(s, v.branch_id, data)
    today = tehran_today()
    fy = open_year_for(s, today)
    now = utcnow()
    o = SalesOrder(
        id=data.id,
        branch_id=v.branch_id,
        warehouse_id=wh,
        fiscal_year_id=fy.id,
        visitor_id=v.id,
        customer_id=data.customer_id,
        number=next_number(s, "sales_order", fy.id, v.branch_id),
        status="submitted",
        ordered_at=min(data.ordered_at, now),
        received_at=now,
        subtotal=cart.subtotal,
        discount_total=cart.discount_total,
        tax_total=cart.tax_total,
        grand_total=cart.grand_total,
        client_total=data.client_total,
        note=data.note,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    for ln in cart.lines:
        o.lines.append(
            SalesOrderLine(
                line_no=ln.line_no,
                item_id=ln.item.id,
                unit_id=ln.unit_id,
                qty=ln.qty,
                base_qty=ln.base_qty,
                unit_price=ln.unit_price,
                gross=ln.gross,
                promotion_id=ln.promotion.id if ln.promotion else None,
                promotion_discount=ln.promotion_discount,
                vat_exempt=ln.vat_exempt,
                vat_rate=ln.vat_rate,
                tax=ln.tax,
                revenue=ln.revenue,
                line_total=ln.line_total,
            )
        )
    s.add(o)
    s.flush()
    s.refresh(o)
    return order_out(s, o, cart.warnings), True


def my_orders(s: Session, actor: Actor, days: int = 60) -> list[OrderOut]:
    v = visitors.of_actor(s, actor)
    since = utcnow() - timedelta(days=days)
    rows = list(
        s.scalars(
            select(SalesOrder)
            .where(SalesOrder.visitor_id == v.id, SalesOrder.received_at >= since)
            .order_by(SalesOrder.received_at.desc())
            .limit(200)
        )
    )
    return [order_out(s, o) for o in rows]


def cancel_own(s: Session, actor: Actor, order_id: uuid.UUID) -> OrderOut:
    v = visitors.of_actor(s, actor)
    o = s.get(SalesOrder, order_id, with_for_update=True)
    if o is None or o.visitor_id != v.id:
        raise NotFoundError("سفارش یافت نشد")
    if o.status != "submitted":
        raise ConflictError("فقط سفارش بررسی‌نشده لغو می‌شود", code="not_cancellable")
    o.status, o.decided_by, o.decided_at = "cancelled", actor.user_id, utcnow()
    o.decision_note = "لغو توسط ویزیتور"
    o.updated_by = actor.user_id
    s.flush()
    s.refresh(o)
    return order_out(s, o)


def record_visit(s: Session, actor: Actor, data: VisitIn) -> tuple[VisitOut, bool]:
    v = visitors.of_actor(s, actor)
    found = s.get(Visit, data.id)
    if found is not None:
        if found.visitor_id != v.id:
            raise ConflictError("این شناسه بازدید قبلاً استفاده شده است", code="visit_exists")
        return _visit_out(s, found), False
    if not visitors.is_assigned(s, v.id, data.customer_id):
        raise PermissionDeniedError("این مشتری به شما تخصیص داده نشده است", code="not_assigned")
    if data.order_id is not None:
        o = s.get(SalesOrder, data.order_id)
        if o is None or o.visitor_id != v.id:
            raise NotFoundError("سفارش یافت نشد")
    now = utcnow()
    visit = Visit(
        id=data.id,
        visitor_id=v.id,
        customer_id=data.customer_id,
        visited_at=min(data.visited_at, now),
        received_at=now,
        outcome=data.outcome,
        note=data.note,
        order_id=data.order_id,
    )
    s.add(visit)
    s.flush()
    return _visit_out(s, visit), True


def _visit_out(s: Session, visit: Visit) -> VisitOut:
    v = s.get(Visitor, visit.visitor_id)
    c = s.get(DetailAccount, visit.customer_id)
    return VisitOut(
        id=visit.id,
        visitor_name=(_name(s, v.user_id) or "") if v else "",
        customer_id=visit.customer_id,
        customer_name=c.name if c else "",
        visited_at=visit.visited_at,
        received_at=visit.received_at,
        outcome=visit.outcome,  # type: ignore[arg-type]
        note=visit.note,
        order_id=visit.order_id,
    )


# --- back office ---------------------------------------------------------------------------


def _get(s: Session, actor: Actor, order_id: uuid.UUID, lock: bool = False) -> SalesOrder:
    o = s.get(SalesOrder, order_id, with_for_update=lock)
    if o is None or not actor.can_access_branch(o.branch_id):
        raise NotFoundError("سفارش یافت نشد")
    return o


def _range(d_from: object, d_to: object) -> tuple[datetime | None, datetime | None]:
    def at(d: object, end: bool) -> datetime | None:
        if d is None:
            return None
        local = datetime.combine(d, time.min, tzinfo=TEHRAN)  # type: ignore[arg-type]
        return (local + timedelta(days=1) if end else local).astimezone(UTC)

    return at(d_from, False), at(d_to, True)


def list_orders(s: Session, actor: Actor, q: OrderQuery) -> Page[OrderSummaryOut]:
    stmt = select(SalesOrder)
    if actor.branch_ids is not None:
        stmt = stmt.where(SalesOrder.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    if q.status == "open":
        stmt = stmt.where(SalesOrder.status.in_(OPEN))
    elif q.status:
        stmt = stmt.where(SalesOrder.status == q.status)
    if q.visitor_id:
        stmt = stmt.where(SalesOrder.visitor_id == q.visitor_id)
    start, end = _range(q.date_from, q.date_to)
    if start:
        stmt = stmt.where(SalesOrder.received_at >= start)
    if end:
        stmt = stmt.where(SalesOrder.received_at < end)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(SalesOrder.received_at.desc(), SalesOrder.id)
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    return Page(
        items=[_summary(s, o) for o in rows], total=total, page=q.page, page_size=q.page_size
    )


def get(s: Session, actor: Actor, order_id: uuid.UUID) -> OrderOut:
    return order_out(s, _get(s, actor, order_id))


def _decide(o: SalesOrder, actor: Actor, status: str, note: str | None) -> None:
    o.status, o.decided_by, o.decided_at, o.decision_note = status, actor.user_id, utcnow(), note
    o.updated_by = actor.user_id


def _audit(s: Session, actor: Actor, o: SalesOrder, action: str, **data: object) -> None:
    audit.record(
        s,
        f"distribution.order_{action}",
        user_id=actor.user_id,
        branch_id=o.branch_id,
        entity_type="sales_order",
        entity_id=o.id,
        data={"number": o.number, "total": str(o.grand_total), **data},
    )


def approve(
    s: Session, actor: Actor, order_id: uuid.UUID, data: DecisionIn, version: str
) -> OrderOut:
    o = _get(s, actor, order_id, lock=True)
    check_version(o.row_version, version, "این سفارش")
    if o.status != "submitted":
        raise ConflictError("فقط سفارش بررسی‌نشده تأیید می‌شود", code="not_submitted")
    _check_credit(s, o)
    _decide(o, actor, "approved", data.note)
    s.flush()
    _audit(s, actor, o, "approved")
    s.refresh(o)
    return order_out(s, o)


def reject(s: Session, actor: Actor, order_id: uuid.UUID, data: RejectIn, version: str) -> OrderOut:
    o = _get(s, actor, order_id, lock=True)
    check_version(o.row_version, version, "این سفارش")
    if o.status not in OPEN:
        raise ConflictError("این سفارش دیگر قابل رد نیست", code="not_open")
    _decide(o, actor, "rejected", data.note)
    s.flush()
    _audit(s, actor, o, "rejected", note=data.note)
    s.refresh(o)
    return order_out(s, o)


def invoice(
    s: Session, actor: Actor, order_id: uuid.UUID, data: InvoiceOrderIn, version: str
) -> OrderOut:
    """Turn an approved order into a final credit sales invoice (stock, voucher, number)."""
    o = _get(s, actor, order_id, lock=True)
    check_version(o.row_version, version, "این سفارش")
    if o.status != "approved":
        raise ConflictError("فقط سفارش تأییدشده فاکتور می‌شود", code="not_approved")
    reg = s.get(CashRegister, data.cash_register_id)
    if reg is None or reg.branch_id != o.branch_id or not reg.is_active:
        raise NotFoundError("صندوق یافت نشد (باید از همان شعبه و فعال باشد)")
    _check_credit(s, o)
    org = pricing.organization(s)
    today = tehran_today()
    fy = open_year_for(s, today)
    inv = SalesInvoice(
        branch_id=o.branch_id,
        cash_register_id=reg.id,
        shift_id=None,
        fiscal_year_id=fy.id,
        warehouse_id=o.warehouse_id,
        kind="sale",
        status="draft",
        document_date=today,
        customer_id=o.customer_id,
        subtotal=o.subtotal,
        discount_total=o.discount_total,
        tax_total=o.tax_total,
        grand_total=o.grand_total,
        note=f"سفارش ویزیتور شماره {o.number}",
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(inv)
    items = {
        i.id: i for i in s.scalars(select(Item).where(Item.id.in_({ln.item_id for ln in o.lines})))
    }
    lines = []
    for ln in o.lines:
        row = SalesInvoiceLine(
            line_no=ln.line_no,
            item_id=ln.item_id,
            unit_id=ln.unit_id,
            qty=ln.qty,
            base_qty=ln.base_qty,
            unit_price=ln.unit_price,
            price_source="list",
            gross=ln.gross,
            promotion_id=ln.promotion_id,
            promotion_discount=ln.promotion_discount,
            manual_discount=ZERO,
            vat_exempt=ln.vat_exempt,
            vat_rate=ln.vat_rate,
            tax=ln.tax,
            revenue=ln.revenue,
            line_total=ln.line_total,
        )
        inv.lines.append(row)
        lines.append((row, pricing.item_ref(items[ln.item_id])))
    if o.grand_total > 0:
        inv.payments.append(SalesPayment(seq=1, method="credit", amount=o.grand_total))
    s.flush()
    book_sale(
        s,
        inv,
        lines,
        _Tender(credit=o.grand_total),
        fiscal_year_id=fy.id,
        register_name=reg.name,
        allow_negative=org.negative_stock_policy != "deny",
        actor_id=actor.user_id,
        stock_date=today,
    )
    o.status, o.invoice_id, o.updated_by = "invoiced", inv.id, actor.user_id
    s.flush()
    _audit(s, actor, o, "invoiced", invoice=inv.number)
    s.refresh(o)
    return order_out(s, o)


def deliver(
    s: Session, actor: Actor, order_id: uuid.UUID, data: DecisionIn, version: str
) -> OrderOut:
    o = _get(s, actor, order_id, lock=True)
    check_version(o.row_version, version, "این سفارش")
    if o.status != "invoiced":
        raise ConflictError("فقط سفارش فاکتورشده تحویل می‌شود", code="not_invoiced")
    o.status, o.delivered_at, o.delivered_by = "delivered", utcnow(), actor.user_id
    if data.note:
        o.decision_note = data.note
    o.updated_by = actor.user_id
    s.flush()
    _audit(s, actor, o, "delivered")
    s.refresh(o)
    return order_out(s, o)


def list_visits(
    s: Session, actor: Actor, visitor_id: uuid.UUID | None, d_from: object, d_to: object
) -> list[VisitOut]:
    stmt = select(Visit).join(Visitor, Visitor.id == Visit.visitor_id)
    if actor.branch_ids is not None:
        stmt = stmt.where(Visitor.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    if visitor_id:
        stmt = stmt.where(Visit.visitor_id == visitor_id)
    start, end = _range(d_from, d_to)
    if start:
        stmt = stmt.where(Visit.visited_at >= start)
    if end:
        stmt = stmt.where(Visit.visited_at < end)
    rows = list(s.scalars(stmt.order_by(Visit.visited_at.desc()).limit(500)))
    return [_visit_out(s, v) for v in rows]
