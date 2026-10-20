"""Purchase orders: draft → approved → closed (or cancelled). No stock or accounting effect."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import version_to_str
from app.core.errors import DomainError, NotFoundError
from app.core.http import Page
from app.core.numbering import next_number
from app.modules.accounting.models import DetailAccount
from app.modules.accounting.services.chart import check_version
from app.modules.accounting.services.fiscal import open_year_for
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.inventory.models import Item, Unit, Warehouse
from app.modules.purchasing.models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.modules.purchasing.schemas import (
    OrderIn,
    OrderLineOut,
    OrderOut,
    OrderQuery,
    OrderSummary,
)
from app.modules.purchasing.services import common
from app.modules.purchasing.services.common import ZERO, rial


def received(s: Session, line_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Base quantity received per order line on final invoices, net of returns.

    Return lines carry the order line of the invoice line they return.
    """
    if not line_ids:
        return {}
    got: dict[uuid.UUID, Decimal] = {}
    for oid, qty, kind in s.execute(
        select(
            PurchaseInvoiceLine.order_line_id, PurchaseInvoiceLine.base_qty, PurchaseInvoice.kind
        )
        .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.invoice_id)
        .where(PurchaseInvoice.status == "final", PurchaseInvoiceLine.order_line_id.in_(line_ids))
    ).all():
        if oid is None:
            continue
        got[oid] = got.get(oid, ZERO) + (qty if kind == "invoice" else -qty)
    return got


def _estimate(o: PurchaseOrder) -> Decimal:
    return sum((rial(ln.qty * ln.unit_cost) for ln in o.lines if ln.unit_cost is not None), ZERO)


def order_out(s: Session, o: PurchaseOrder) -> OrderOut:
    items = {
        i.id: i for i in s.scalars(select(Item).where(Item.id.in_({ln.item_id for ln in o.lines})))
    }
    units = common.names(s, Unit, {ln.unit_id for ln in o.lines})
    got = received(s, [ln.id for ln in o.lines])
    wh = s.get(Warehouse, o.warehouse_id)
    sup = s.get(DetailAccount, o.supplier_id)
    return OrderOut(
        id=o.id,
        number=o.number,
        status=o.status,
        branch_id=o.branch_id,
        warehouse_id=o.warehouse_id,
        warehouse_name=wh.name if wh else "",
        supplier_id=o.supplier_id,
        supplier_name=sup.name if sup else "",
        order_date=o.order_date,
        expected_date=o.expected_date,
        note=o.note,
        estimated_total=_estimate(o),
        lines=[
            OrderLineOut(
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
                received_base_qty=got.get(ln.id, ZERO),
            )
            for ln in o.lines
        ],
        created_at=o.created_at,
        row_version=version_to_str(o.row_version),
    )


def _apply(s: Session, actor: Actor, o: PurchaseOrder, data: OrderIn) -> None:
    wh = common.warehouse(s, actor, data.warehouse_id)
    common.supplier(s, data.supplier_id)
    if data.expected_date and data.expected_date < data.order_date:
        raise DomainError("تاریخ تحویل نمی‌تواند پیش از تاریخ سفارش باشد", code="bad_dates")
    items = common.items(s, {ln.item_id for ln in data.lines})
    o.branch_id, o.warehouse_id, o.supplier_id = wh.branch_id, wh.id, data.supplier_id
    o.order_date, o.expected_date, o.note = data.order_date, data.expected_date, data.note
    if o.lines:
        o.lines.clear()
        s.flush()
    for n, ln in enumerate(data.lines, start=1):
        item = items[ln.item_id]
        unit_id = ln.unit_id or item.base_unit_id
        o.lines.append(
            PurchaseOrderLine(
                line_no=n,
                item_id=item.id,
                unit_id=unit_id,
                qty=ln.qty,
                base_qty=common.base_qty(s, item, unit_id, ln.qty),
                unit_cost=ln.unit_cost,
            )
        )


def create(s: Session, actor: Actor, data: OrderIn) -> OrderOut:
    o = PurchaseOrder(status="draft", created_by=actor.user_id, updated_by=actor.user_id)
    _apply(s, actor, o, data)
    s.add(o)
    s.flush()
    audit.record(
        s,
        "purchasing.order_created",
        user_id=actor.user_id,
        branch_id=o.branch_id,
        entity_type="purchase_order",
        entity_id=o.id,
    )
    return order_out(s, o)


def _get(s: Session, actor: Actor, order_id: uuid.UUID, lock: bool = False) -> PurchaseOrder:
    o = s.get(PurchaseOrder, order_id, with_for_update=lock)
    if o is None or not actor.can_access_branch(o.branch_id):
        raise NotFoundError("سفارش خرید یافت نشد")
    return o


def get(s: Session, actor: Actor, order_id: uuid.UUID) -> OrderOut:
    return order_out(s, _get(s, actor, order_id))


def update(s: Session, actor: Actor, order_id: uuid.UUID, data: OrderIn, version: str) -> OrderOut:
    o = _get(s, actor, order_id, lock=True)
    check_version(o.row_version, version, "این سفارش")
    if o.status != "draft":
        raise DomainError("فقط سفارش پیش‌نویس ویرایش می‌شود", code="order_not_draft")
    _apply(s, actor, o, data)
    o.updated_by = actor.user_id
    s.flush()
    return order_out(s, o)


def set_status(
    s: Session, actor: Actor, order_id: uuid.UUID, action: str, version: str
) -> OrderOut:
    o = _get(s, actor, order_id, lock=True)
    check_version(o.row_version, version, "این سفارش")
    allowed = {
        "approve": ("draft", "approved"),
        "cancel": ("draft", "cancelled"),
        "close": ("approved", "closed"),
    }
    src, dst = allowed[action]
    if action == "cancel" and o.status == "approved":
        # An approved order with nothing received may still be cancelled.
        if any(received(s, [ln.id for ln in o.lines]).values()):
            raise DomainError("بخشی از سفارش دریافت شده؛ آن را ببندید", code="order_received")
    elif o.status != src:
        raise DomainError("این تغییر وضعیت برای سفارش مجاز نیست", code="bad_order_status")
    if action == "approve":
        fy = open_year_for(s, o.order_date)
        o.fiscal_year_id = fy.id
        o.number = next_number(s, "purchase_order", fy.id, o.branch_id)
    o.status = dst
    o.updated_by = actor.user_id
    s.flush()
    audit.record(
        s,
        f"purchasing.order_{action}",
        user_id=actor.user_id,
        branch_id=o.branch_id,
        entity_type="purchase_order",
        entity_id=o.id,
    )
    return order_out(s, o)


def close_if_received(s: Session, o: PurchaseOrder) -> None:
    got = received(s, [ln.id for ln in o.lines])
    if all(got.get(ln.id, ZERO) >= ln.base_qty for ln in o.lines):
        o.status = "closed"


def list_orders(s: Session, actor: Actor, q: OrderQuery) -> Page[OrderSummary]:
    stmt = select(PurchaseOrder)
    if actor.branch_ids is not None:
        stmt = stmt.where(PurchaseOrder.branch_id.in_(actor.branch_ids))
    if q.status:
        stmt = stmt.where(PurchaseOrder.status == q.status)
    if q.supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == q.supplier_id)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc())
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    sups = common.names(s, DetailAccount, {o.supplier_id for o in rows})
    whs = common.names(s, Warehouse, {o.warehouse_id for o in rows})
    return Page(
        items=[
            OrderSummary(
                id=o.id,
                number=o.number,
                status=o.status,
                supplier_name=sups.get(o.supplier_id, ""),
                warehouse_name=whs.get(o.warehouse_id, ""),
                order_date=o.order_date,
                expected_date=o.expected_date,
                estimated_total=_estimate(o),
            )
            for o in rows
        ],
        total=total,
        page=q.page,
        page_size=q.page_size,
    )
