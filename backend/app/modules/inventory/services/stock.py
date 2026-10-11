"""Stock movements, moving weighted average cost and stock documents (ADR-0007, ADR-0012).

Quantity changes only through ``post_movement`` → ``stock_ledger`` + ``stock_balance``,
in the same transaction as the document and its accounting voucher.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.http import Page
from app.core.money import MONEY_PLACES, ZERO
from app.core.numbering import next_number
from app.modules.accounting.models import Voucher
from app.modules.accounting.services.chart import check_version
from app.modules.accounting.services.fiscal import open_year_for
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.inventory.models import (
    Item,
    ItemUnit,
    StockBalance,
    StockDocument,
    StockDocumentLine,
    StockLedger,
    Unit,
    Warehouse,
)
from app.modules.inventory.schemas import (
    BalanceRow,
    KardexRow,
    StockDocIn,
    StockDocOut,
    StockDocSummary,
    StockLineOut,
)

COST_PLACES = Decimal("0.000001")
QTY_PLACES = Decimal("0.001")
DOC_TYPE = "stock"
DOC_LABEL = {
    "opening": "موجودی اول دوره",
    "adjustment": "تعدیل موجودی",
    "transfer": "انتقال بین انبارها",
    "count": "شمارش موجودی",
}


def _money(d: Decimal) -> Decimal:
    return d.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def tehran_today() -> date:
    from zoneinfo import ZoneInfo

    return utcnow().astimezone(ZoneInfo("Asia/Tehran")).date()


# --- costing engine ---------------------------------------------------------


@dataclass(frozen=True)
class Posted:
    qty: Decimal
    value: Decimal


def _lock_balance(s: Session, item_id: uuid.UUID, warehouse_id: uuid.UUID) -> StockBalance:
    """Row-locked balance, created on first movement.

    Callers lock in (item, warehouse) order to avoid deadlocks.
    """
    s.execute(
        text(
            "IF NOT EXISTS (SELECT 1 FROM stock_balance WITH (UPDLOCK, HOLDLOCK) "
            "WHERE item_id = :i AND warehouse_id = :w) "
            "INSERT INTO stock_balance (item_id, warehouse_id, qty, value, avg_cost) "
            "VALUES (:i, :w, 0, 0, 0)"
        ),
        {"i": item_id, "w": warehouse_id},
    )
    bal = s.scalar(
        select(StockBalance)
        .where(StockBalance.item_id == item_id, StockBalance.warehouse_id == warehouse_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert bal is not None
    return bal


def post_movement(
    s: Session,
    *,
    item_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    qty: Decimal,
    unit_cost: Decimal | None,
    document: StockDocument,
    line: StockDocumentLine,
    allow_negative: bool = False,
    value: Decimal | None = None,
) -> Posted:
    """qty > 0 receipt at ``unit_cost`` (base unit) or exactly ``value``; qty < 0 issue at average.

    Returns the movement value (positive for receipts, negative for issues).
    """
    bal = _lock_balance(s, item_id, warehouse_id)
    if bal.last_movement_date and document.document_date < bal.last_movement_date:
        raise DomainError(
            "تاریخ سند قبل از آخرین گردش این کالا در این انبار است؛ "
            "ثبت سند با تاریخ گذشته پشتیبانی نمی‌شود",
            code="backdated_stock",
        )
    if qty > 0:
        if unit_cost is None:
            unit_cost = bal.avg_cost
        if unit_cost < 0:
            raise DomainError("بهای واحد نمی‌تواند منفی باشد", code="negative_cost")
        value = value if value is not None else _money(qty * unit_cost)
        bal.qty += qty
        bal.value += value
        bal.avg_cost = (bal.value / bal.qty).quantize(COST_PLACES) if bal.qty > 0 else unit_cost
        entry = StockLedger(qty_in=qty, value_in=value)
        posted = Posted(qty, value)
    else:
        out = -qty
        if bal.qty < out and not allow_negative:
            item = s.get(Item, item_id)
            raise DomainError(
                f"موجودی «{item.name if item else ''}» کافی نیست "
                f"(موجود: {bal.qty.normalize():f}، درخواست: {out.normalize():f})",
                code="insufficient_stock",
            )
        # Taking the last units takes the remaining value exactly (no rounding residue).
        value = bal.value if out == bal.qty else _money(out * bal.avg_cost)
        bal.qty -= out
        bal.value -= value
        entry = StockLedger(qty_out=out, value_out=value)
        posted = Posted(qty, -value)
    bal.last_movement_date = document.document_date
    entry.item_id, entry.warehouse_id = item_id, warehouse_id
    entry.document_id, entry.document_line_id = document.id, line.id
    entry.document_date = document.document_date
    entry.balance_qty, entry.balance_value, entry.avg_cost = bal.qty, bal.value, bal.avg_cost
    s.add(entry)
    return posted


# --- documents --------------------------------------------------------------


def _warehouse(s: Session, actor: Actor | None, wid: uuid.UUID) -> Warehouse:
    w = s.get(Warehouse, wid)
    if (
        w is None
        or not w.is_active
        or (actor is not None and not actor.can_access_branch(w.branch_id))
    ):
        raise NotFoundError("انبار یافت نشد")
    return w


def _factor(s: Session, item: Item, unit_id: uuid.UUID) -> Decimal:
    if unit_id == item.base_unit_id:
        return Decimal(1)
    f = s.scalar(
        select(ItemUnit.factor).where(ItemUnit.item_id == item.id, ItemUnit.unit_id == unit_id)
    )
    if f is None:
        raise DomainError(f"واحد انتخاب‌شده برای «{item.name}» تعریف نشده است", code="invalid_unit")
    return Decimal(f)


def _build_lines(s: Session, doc: StockDocument, data: StockDocIn) -> None:
    items = {
        i.id: i
        for i in s.scalars(select(Item).where(Item.id.in_({ln.item_id for ln in data.lines})))
    }
    if doc.lines:
        doc.lines.clear()
        s.flush()
    seen: set[uuid.UUID] = set()
    for n, ln in enumerate(data.lines, start=1):
        item = items.get(ln.item_id)
        if item is None:
            raise DomainError(f"ردیف {n}: کالا یافت نشد", code="invalid_item")
        if item.item_type != "goods":
            raise DomainError(
                f"ردیف {n}: «{item.name}» خدمت است و موجودی ندارد", code="not_stock_item"
            )
        if data.doc_type == "count":
            if item.id in seen:
                raise DomainError(
                    f"ردیف {n}: «{item.name}» در برگه شمارش تکرار شده است", code="duplicate_line"
                )
            seen.add(item.id)
            if ln.qty < 0:
                raise DomainError(f"ردیف {n}: مقدار شمارش منفی است", code="invalid_qty")
        elif data.doc_type == "adjustment":
            if ln.qty == 0:
                raise DomainError(f"ردیف {n}: مقدار تعدیل صفر است", code="invalid_qty")
        elif ln.qty <= 0:
            raise DomainError(f"ردیف {n}: مقدار باید مثبت باشد", code="invalid_qty")
        unit_id = ln.unit_id or item.base_unit_id
        factor = _factor(s, item, unit_id)
        unit = s.get(Unit, unit_id)
        base_qty = (ln.qty * factor).quantize(QTY_PLACES, rounding=ROUND_HALF_UP)
        if unit is not None and not unit.allows_fraction and ln.qty != ln.qty.to_integral_value():
            raise DomainError(
                f"ردیف {n}: مقدار «{unit.name}» باید عدد صحیح باشد", code="invalid_qty"
            )
        if data.doc_type == "opening" and ln.unit_cost is None:
            raise DomainError(
                f"ردیف {n}: بهای واحد برای موجودی اول دوره الزامی است", code="cost_required"
            )
        if item.track_expiry and data.doc_type in ("opening",) and ln.expiry_date is None:
            raise DomainError(
                f"ردیف {n}: تاریخ انقضای «{item.name}» الزامی است", code="expiry_required"
            )
        doc.lines.append(
            StockDocumentLine(
                line_no=n,
                item_id=item.id,
                unit_id=unit_id,
                qty=ln.qty,
                base_qty=base_qty,
                unit_cost=ln.unit_cost,
                expiry_date=ln.expiry_date,
                description=ln.description,
            )
        )


def _check_header(s: Session, actor: Actor, data: StockDocIn) -> Warehouse:
    wh = _warehouse(s, actor, data.warehouse_id)
    if data.doc_type == "transfer":
        if data.dest_warehouse_id is None or data.dest_warehouse_id == data.warehouse_id:
            raise DomainError("انبار مقصد را انتخاب کنید (متفاوت از مبدأ)", code="dest_required")
        _warehouse(s, actor, data.dest_warehouse_id)
    elif data.dest_warehouse_id is not None:
        raise DomainError("انبار مقصد فقط برای انتقال است", code="invalid_dest")
    if data.document_date > tehran_today():
        raise DomainError("تاریخ سند انبار نمی‌تواند در آینده باشد", code="future_date")
    if data.doc_type == "adjustment" and not actor.has("inventory.stock.adjust"):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("ثبت تعدیل موجودی نیازمند مجوز «تعدیل موجودی» است")
    return wh


def doc_out(s: Session, d: StockDocument) -> StockDocOut:
    items = (
        {
            i.id: i
            for i in s.scalars(select(Item).where(Item.id.in_({ln.item_id for ln in d.lines})))
        }
        if d.lines
        else {}
    )
    units = {u.id: u.name for u in s.scalars(select(Unit))}
    voucher_number = (
        s.scalar(select(Voucher.number).where(Voucher.id == d.voucher_id)) if d.voucher_id else None
    )
    total = sum((ln.total_cost or ZERO for ln in d.lines), ZERO) if d.status == "final" else None
    return StockDocOut(
        id=d.id,
        branch_id=d.branch_id,
        warehouse_id=d.warehouse_id,
        dest_warehouse_id=d.dest_warehouse_id,
        doc_type=d.doc_type,  # type: ignore[arg-type]
        number=d.number,
        document_date=d.document_date,
        status=d.status,  # type: ignore[arg-type]
        description=d.description,
        voucher_id=d.voucher_id,
        voucher_number=voucher_number,
        source_document_id=d.source_document_id,
        total_value=total,
        finalized_at=d.finalized_at,
        row_version=version_to_str(d.row_version),
        lines=[
            StockLineOut(
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
                total_cost=ln.total_cost,
                system_qty=ln.system_qty,
                expiry_date=ln.expiry_date,
                description=ln.description,
            )
            for ln in d.lines
        ],
    )


def get_doc(s: Session, actor: Actor | None, doc_id: uuid.UUID) -> StockDocument:
    d = s.get(StockDocument, doc_id)
    if d is None or (actor is not None and not actor.can_access_branch(d.branch_id)):
        raise NotFoundError("سند انبار یافت نشد")
    return d


def create_doc(s: Session, actor: Actor, data: StockDocIn) -> StockDocOut:
    wh = _check_header(s, actor, data)
    fy = open_year_for(s, data.document_date)
    d = StockDocument(
        branch_id=wh.branch_id,
        warehouse_id=wh.id,
        dest_warehouse_id=data.dest_warehouse_id,
        fiscal_year_id=fy.id,
        doc_type=data.doc_type,
        document_date=data.document_date,
        status="draft",
        description=data.description,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(d)
    _build_lines(s, d, data)
    s.flush()
    audit.record(
        s,
        "inventory.stock_doc_created",
        user_id=actor.user_id,
        entity_type="stock_document",
        entity_id=d.id,
        branch_id=d.branch_id,
        data={"type": d.doc_type, "lines": len(d.lines)},
    )
    return doc_out(s, d)


def update_doc(
    s: Session, actor: Actor, doc_id: uuid.UUID, data: StockDocIn, version: str
) -> StockDocOut:
    d = get_doc(s, actor, doc_id)
    check_version(d.row_version, version, "این سند")
    if d.status != "draft":
        raise DomainError("سند قطعی انبار قابل ویرایش نیست", code="doc_final")
    if data.doc_type != d.doc_type:
        raise DomainError("نوع سند قابل تغییر نیست", code="invalid_type")
    wh = _check_header(s, actor, data)
    d.branch_id, d.warehouse_id, d.dest_warehouse_id = wh.branch_id, wh.id, data.dest_warehouse_id
    d.document_date, d.description = data.document_date, data.description
    d.fiscal_year_id = open_year_for(s, data.document_date).id
    _build_lines(s, d, data)
    d.updated_by, d.updated_at = actor.user_id, utcnow()
    s.flush()
    s.refresh(d)
    return doc_out(s, d)


def delete_doc(s: Session, actor: Actor, doc_id: uuid.UUID, version: str) -> None:
    d = get_doc(s, actor, doc_id)
    check_version(d.row_version, version, "این سند")
    if d.status != "draft":
        raise DomainError("سند قطعی انبار حذف نمی‌شود", code="doc_final")
    audit.record(
        s,
        "inventory.stock_doc_deleted",
        user_id=actor.user_id,
        entity_type="stock_document",
        entity_id=d.id,
        branch_id=d.branch_id,
    )
    s.delete(d)
    s.flush()


def _sorted_lines(d: StockDocument) -> list[StockDocumentLine]:
    # A fixed lock order (item id) prevents deadlocks between concurrent documents.
    return sorted(d.lines, key=lambda ln: str(ln.item_id))


def finalize_doc(s: Session, actor: Actor, doc_id: uuid.UUID, version: str) -> StockDocOut:
    d = get_doc(s, actor, doc_id)
    check_version(d.row_version, version, "این سند")
    if d.status != "draft":
        raise DomainError("این سند قبلاً قطعی شده است", code="doc_final")
    if d.doc_type == "adjustment" and not actor.has("inventory.stock.adjust"):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("قطعی کردن تعدیل موجودی نیازمند مجوز «تعدیل موجودی» است")
    if d.document_date > tehran_today():
        raise DomainError("تاریخ سند انبار نمی‌تواند در آینده باشد", code="future_date")
    open_year_for(s, d.document_date)

    if d.doc_type == "count":
        adjustment = _finalize_count(s, actor, d)
    else:
        _post_document(s, actor, d)
        adjustment = None
    d.number = next_number(s, DOC_TYPE, d.fiscal_year_id, d.branch_id)
    d.status = "final"
    d.finalized_at = utcnow()
    d.updated_by, d.updated_at = actor.user_id, utcnow()
    s.flush()
    audit.record(
        s,
        "inventory.stock_doc_finalized",
        user_id=actor.user_id,
        entity_type="stock_document",
        entity_id=d.id,
        branch_id=d.branch_id,
        data={
            "type": d.doc_type,
            "number": d.number,
            "adjustment_id": str(adjustment.id) if adjustment else None,
        },
    )
    s.refresh(d)
    return doc_out(s, d)


def _post_document(s: Session, actor: Actor, d: StockDocument) -> None:
    surplus = shortage = opening = ZERO
    for ln in _sorted_lines(d):
        item = s.get(Item, ln.item_id)
        assert item is not None
        factor = _factor(s, item, ln.unit_id)
        base_cost = (
            (ln.unit_cost / factor).quantize(COST_PLACES) if ln.unit_cost is not None else None
        )
        if d.doc_type == "opening":
            posted = post_movement(
                s,
                item_id=item.id,
                warehouse_id=d.warehouse_id,
                qty=ln.base_qty,
                unit_cost=base_cost,
                document=d,
                line=ln,
            )
            opening += posted.value
            ln.total_cost = posted.value
        elif d.doc_type == "adjustment":
            if ln.base_qty > 0:
                bal_cost = s.scalar(
                    select(StockBalance.avg_cost).where(
                        StockBalance.item_id == item.id, StockBalance.warehouse_id == d.warehouse_id
                    )
                )
                if base_cost is None and not bal_cost:
                    raise DomainError(
                        f"«{item.name}» بهای تمام‌شده ندارد؛ بهای واحد اضافه را وارد کنید",
                        code="cost_required",
                    )
            posted = post_movement(
                s,
                item_id=item.id,
                warehouse_id=d.warehouse_id,
                qty=ln.base_qty,
                unit_cost=base_cost if ln.base_qty > 0 else None,
                document=d,
                line=ln,
            )
            ln.total_cost = posted.value
            if posted.value >= 0:
                surplus += posted.value
            else:
                shortage += -posted.value
        else:  # transfer: out of source at average, into destination at the same value
            out = post_movement(
                s,
                item_id=item.id,
                warehouse_id=d.warehouse_id,
                qty=-ln.base_qty,
                unit_cost=None,
                document=d,
                line=ln,
            )
            value = -out.value
            unit = (value / ln.base_qty).quantize(COST_PLACES)
            # The exact value moves, so total stock value is unchanged by a transfer.
            post_movement(
                s,
                item_id=item.id,
                warehouse_id=d.dest_warehouse_id,  # type: ignore[arg-type]
                qty=ln.base_qty,
                unit_cost=unit,
                value=value,
                document=d,
                line=ln,
            )
            ln.total_cost = value

    entries: list[Entry] = []
    if d.doc_type == "opening" and opening:
        entries = [Entry("inventory", debit=opening), Entry("offset", credit=opening)]
        event = "inventory.opening.finalized"
    elif d.doc_type == "adjustment" and (surplus or shortage):
        entries = [
            Entry("inventory", debit=surplus, credit=ZERO),
            Entry("surplus", credit=surplus),
            Entry("shortage", debit=shortage),
            Entry("inventory", credit=shortage),
        ]
        event = "inventory.adjustment.finalized"
    if entries:
        v = post_event(
            s,
            event_type=event,
            document_date=d.document_date,
            branch_id=d.branch_id,
            entries=entries,
            actor_id=actor.user_id,
            source_id=d.id,
            description=f"{DOC_LABEL[d.doc_type]} — {d.description or ''}".strip(" —"),
        )
        d.voucher_id = v.id


def _finalize_count(s: Session, actor: Actor, count: StockDocument) -> StockDocument | None:
    """Freeze system quantities, then post the differences as an adjustment document."""
    if not actor.has("inventory.stock.adjust"):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("قطعی کردن شمارش نیازمند مجوز «تعدیل موجودی» است")
    diffs = []
    for ln in _sorted_lines(count):
        bal = _lock_balance(s, ln.item_id, count.warehouse_id)
        ln.system_qty = bal.qty
        delta = ln.base_qty - bal.qty
        if delta:
            diffs.append((ln, delta))
    if not diffs:
        return None
    adj = StockDocument(
        branch_id=count.branch_id,
        warehouse_id=count.warehouse_id,
        fiscal_year_id=count.fiscal_year_id,
        doc_type="adjustment",
        document_date=count.document_date,
        status="draft",
        description=f"مغایرت شمارش {count.description or ''}".strip(),
        source_document_id=count.id,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(adj)
    for n, (ln, delta) in enumerate(diffs, start=1):
        adj.lines.append(
            StockDocumentLine(
                line_no=n,
                item_id=ln.item_id,
                unit_id=s.get(Item, ln.item_id).base_unit_id,  # type: ignore[union-attr]
                qty=delta,
                base_qty=delta,
                unit_cost=None,
                description="مغایرت شمارش",
            )
        )
    s.flush()
    _post_document(s, actor, adj)
    adj.number = next_number(s, DOC_TYPE, adj.fiscal_year_id, adj.branch_id)
    adj.status, adj.finalized_at = "final", utcnow()
    s.flush()
    return adj


def list_docs(
    s: Session,
    actor: Actor,
    page: int,
    page_size: int,
    doc_type: str | None,
    status: str | None,
    warehouse_id: uuid.UUID | None,
) -> Page[StockDocSummary]:
    n_lines = (
        select(func.count())
        .where(StockDocumentLine.document_id == StockDocument.id)
        .correlate(StockDocument)
        .scalar_subquery()
    )
    stmt = select(StockDocument, n_lines)
    if doc_type:
        stmt = stmt.where(StockDocument.doc_type == doc_type)
    if status:
        stmt = stmt.where(StockDocument.status == status)
    if warehouse_id:
        stmt = stmt.where(StockDocument.warehouse_id == warehouse_id)
    if actor.branch_ids is not None:
        stmt = stmt.where(StockDocument.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = s.execute(
        stmt.order_by(StockDocument.document_date.desc(), StockDocument.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[StockDocSummary](
        items=[
            StockDocSummary(
                id=d.id,
                doc_type=d.doc_type,
                number=d.number,
                document_date=d.document_date,
                status=d.status,
                warehouse_id=d.warehouse_id,
                dest_warehouse_id=d.dest_warehouse_id,
                description=d.description,
                line_count=int(n),
            )
            for d, n in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- reports ----------------------------------------------------------------


def balances(
    s: Session,
    actor: Actor,
    warehouse_id: uuid.UUID | None,
    q: str | None,
    below_min: bool,
    page: int,
    page_size: int,
) -> Page[BalanceRow]:
    stmt = (
        select(StockBalance, Item, Unit.name)
        .join(Item, Item.id == StockBalance.item_id)
        .join(Unit, Unit.id == Item.base_unit_id)
        .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
    )
    if warehouse_id:
        stmt = stmt.where(StockBalance.warehouse_id == warehouse_id)
    if actor.branch_ids is not None:
        stmt = stmt.where(Warehouse.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    if q:
        stmt = stmt.where((Item.code.like(f"{q}%")) | (Item.name.like(f"%{q}%")))
    if below_min:
        stmt = stmt.where(Item.min_qty.is_not(None), StockBalance.qty < Item.min_qty)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = s.execute(stmt.order_by(Item.code).offset((page - 1) * page_size).limit(page_size)).all()
    page_out = Page[BalanceRow](
        items=[
            BalanceRow(
                item_id=it.id,
                item_code=it.code,
                item_name=it.name,
                unit_name=un,
                warehouse_id=b.warehouse_id,
                qty=b.qty,
                avg_cost=b.avg_cost,
                value=b.value,
                min_qty=it.min_qty,
                below_min=it.min_qty is not None and b.qty < it.min_qty,
            )
            for b, it, un in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
    return page_out


def total_value(s: Session, actor: Actor, warehouse_id: uuid.UUID | None) -> Decimal:
    stmt = select(func.coalesce(func.sum(StockBalance.value), 0)).join(
        Warehouse, Warehouse.id == StockBalance.warehouse_id
    )
    if warehouse_id:
        stmt = stmt.where(StockBalance.warehouse_id == warehouse_id)
    if actor.branch_ids is not None:
        stmt = stmt.where(Warehouse.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    return Decimal(s.scalar(stmt) or 0)


def kardex(
    s: Session, actor: Actor, item_id: uuid.UUID, warehouse_id: uuid.UUID, page: int, page_size: int
) -> Page[KardexRow]:
    _warehouse(s, actor, warehouse_id)
    stmt = (
        select(StockLedger, StockDocument.doc_type, StockDocument.number)
        .join(StockDocument, StockDocument.id == StockLedger.document_id)
        .where(StockLedger.item_id == item_id, StockLedger.warehouse_id == warehouse_id)
    )
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = s.execute(
        stmt.order_by(StockLedger.seq).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[KardexRow](
        items=[
            KardexRow(
                document_id=e.document_id,
                doc_type=t,  # type: ignore[arg-type]
                number=n,
                document_date=e.document_date,
                qty_in=e.qty_in,
                qty_out=e.qty_out,
                value_in=e.value_in,
                value_out=e.value_out,
                balance_qty=e.balance_qty,
                balance_value=e.balance_value,
                avg_cost=e.avg_cost,
            )
            for e, t, n in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- warehouses -------------------------------------------------------------


def ensure_default_warehouses(s: Session) -> None:
    from app.modules.organization.models import Branch

    have = {w.branch_id for w in s.scalars(select(Warehouse))}
    for b in list(s.scalars(select(Branch).order_by(Branch.code))):
        if b.id not in have:
            code = f"W{b.code}"[:8]
            if s.scalar(select(Warehouse.id).where(Warehouse.code == code)) is None:
                s.add(Warehouse(branch_id=b.id, code=code, name=f"انبار {b.name}", is_active=True))
    s.flush()


def create_warehouse(
    s: Session, actor: Actor, branch_id: uuid.UUID, code: str, name: str
) -> Warehouse:
    if not actor.can_access_branch(branch_id):
        raise NotFoundError("شعبه یافت نشد")
    if s.scalar(select(Warehouse.id).where(Warehouse.code == code.upper())):
        raise ConflictError("کد انبار تکراری است", code="warehouse_code_taken")
    w = Warehouse(
        branch_id=branch_id,
        code=code.upper(),
        name=name,
        is_active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(w)
    s.flush()
    audit.record(
        s,
        "inventory.warehouse_created",
        user_id=actor.user_id,
        entity_type="warehouse",
        entity_id=w.id,
        branch_id=branch_id,
        data={"code": w.code},
    )
    return w
