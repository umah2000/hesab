"""Inventory reports from the stock ledger (the only source of quantities, rule 6)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select, true
from sqlalchemy.orm import Session

from app.core.db import load_columns_by_ids
from app.core.errors import NotFoundError
from app.modules.iam.guard import Actor
from app.modules.inventory.models import (
    Item,
    StockBalance,
    StockDocumentLine,
    StockLedger,
    Unit,
    Warehouse,
)
from app.modules.inventory.services.stock import tehran_today
from app.modules.reports.schemas import Column, ExpiryQ, ReportTable, SlowQ, StockMovementQ
from app.modules.reports.services.common import ZERO, branches, date_range, m, page, q
from app.modules.sales.models import SalesInvoice, SalesInvoiceLine


def _warehouses(
    s: Session, actor: Actor, branch_id: uuid.UUID | None, warehouse_id: uuid.UUID | None
) -> set[uuid.UUID]:
    scope = branches(actor, branch_id)
    stmt = select(Warehouse.id)
    if scope is not None:
        stmt = stmt.where(Warehouse.branch_id.in_(scope))
    ids = set(s.scalars(stmt))
    if warehouse_id is not None:
        if warehouse_id not in ids:
            raise NotFoundError("انبار یافت نشد")
        return {warehouse_id}
    return ids or {uuid.UUID(int=0)}


def _items(s: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[Any, str]]:
    """(code/name row, base unit name) per item; plain columns, no relationships."""
    if not ids:
        return {}
    units = dict(s.execute(select(Unit.id, Unit.name)).all())
    rows = load_columns_by_ids(s, Item.id, [Item.code, Item.name, Item.base_unit_id], ids)
    return {k: (r, units.get(r.base_unit_id, "")) for k, r in rows.items()}


def stock_movement(s: Session, actor: Actor, p: StockMovementQ) -> ReportTable:
    """گردش کالا: opening, in, out and closing quantity and value per item."""
    start, end = date_range(p.date_from, p.date_to)
    whs = _warehouses(s, actor, p.branch_id, p.warehouse_id)
    before = StockLedger.document_date < start
    inside = StockLedger.document_date >= start
    stmt = (
        select(
            StockLedger.item_id,
            func.sum(case((before, StockLedger.qty_in - StockLedger.qty_out), else_=0)),
            func.sum(case((before, StockLedger.value_in - StockLedger.value_out), else_=0)),
            func.sum(case((inside, StockLedger.qty_in), else_=0)),
            func.sum(case((inside, StockLedger.value_in), else_=0)),
            func.sum(case((inside, StockLedger.qty_out), else_=0)),
            func.sum(case((inside, StockLedger.value_out), else_=0)),
        )
        .where(StockLedger.warehouse_id.in_(whs), StockLedger.document_date <= end)
        .group_by(StockLedger.item_id)
    )
    if p.q:
        like = f"%{p.q}%"
        stmt = stmt.join(Item, Item.id == StockLedger.item_id).where(
            or_(Item.code.like(like), Item.name.like(like))
        )
    raw = list(s.execute(stmt))
    items = _items(s, {r[0] for r in raw})
    rows = []
    tot = [ZERO] * 6
    for item_id, oq, ov, iq, iv, xq, xv in raw:
        vals = [Decimal(x or 0) for x in (oq, ov, iq, iv, xq, xv)]
        if p.only_moved and not (vals[2] or vals[4]):
            continue
        it, unit = items[item_id]
        rows.append(
            {
                "code": it.code,
                "name": it.name,
                "unit": unit,
                "opening_qty": q(vals[0]),
                "opening_value": m(vals[1]),
                "in_qty": q(vals[2]),
                "in_value": m(vals[3]),
                "out_qty": q(vals[4]),
                "out_value": m(vals[5]),
                "closing_qty": q(vals[0] + vals[2] - vals[4]),
                "closing_value": m(vals[1] + vals[3] - vals[5]),
            }
        )
        tot = [a + b for a, b in zip(tot, vals, strict=True)]
    rows.sort(key=lambda r: r["code"])
    return ReportTable(
        key="stock-movement",
        title="گردش کالا",
        columns=[
            Column(key="code", label="کد"),
            Column(key="name", label="کالا"),
            Column(key="unit", label="واحد"),
            Column(key="opening_qty", label="اول دوره", kind="qty"),
            Column(key="opening_value", label="ارزش اول دوره", kind="money"),
            Column(key="in_qty", label="ورود", kind="qty"),
            Column(key="in_value", label="ارزش ورود", kind="money"),
            Column(key="out_qty", label="خروج", kind="qty"),
            Column(key="out_value", label="ارزش خروج", kind="money"),
            Column(key="closing_qty", label="پایان دوره", kind="qty"),
            Column(key="closing_value", label="ارزش پایان دوره", kind="money"),
        ],
        rows=page(rows, p.page, p.page_size),
        totals={
            "code": "جمع",
            "opening_value": m(tot[1]),
            "in_value": m(tot[3]),
            "out_value": m(tot[5]),
            "closing_value": m(tot[1] + tot[3] - tot[5]),
        },
        total_rows=len(rows),
        page=p.page,
        page_size=p.page_size,
        notes=[
            f"از {start.isoformat()} تا {end.isoformat()}؛ "
            "مقادیر به واحد پایه، ارزش به میانگین موزون."
        ],
    )


def _on_hand(s: Session, whs: set[uuid.UUID]) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    return {
        k: (Decimal(qty or 0), Decimal(val or 0))
        for k, qty, val in s.execute(
            select(StockBalance.item_id, func.sum(StockBalance.qty), func.sum(StockBalance.value))
            .where(StockBalance.warehouse_id.in_(whs))
            .group_by(StockBalance.item_id)
            .having(func.sum(StockBalance.qty) > 0)
        )
    }


def slow_moving(s: Session, actor: Actor, p: SlowQ) -> ReportTable:
    """کم‌گردش و راکد: stock on hand against recent sales.

    Dead (راکد) = no sale in the window; slow (کم‌گردش) = stock lasts longer than
    ``cover_days`` at the window's average daily sales.
    """
    whs = _warehouses(s, actor, p.branch_id, p.warehouse_id)
    today = tehran_today()
    since = today - timedelta(days=p.days - 1)
    on_hand = _on_hand(s, whs)
    sold = {
        k: Decimal(v or 0)
        for k, v in s.execute(
            select(
                SalesInvoiceLine.item_id,
                func.sum(
                    case((SalesInvoice.kind == "return", -1), else_=1) * SalesInvoiceLine.base_qty
                ),
            )
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .where(
                SalesInvoice.status == "final",
                SalesInvoice.document_date >= since,
                SalesInvoice.warehouse_id.in_(whs),
            )
            .group_by(SalesInvoiceLine.item_id)
        )
    }
    last_sale = dict(
        s.execute(
            select(SalesInvoiceLine.item_id, func.max(SalesInvoice.document_date))
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .where(
                SalesInvoice.status == "final",
                SalesInvoice.kind == "sale",
                SalesInvoice.warehouse_id.in_(whs),
            )
            .group_by(SalesInvoiceLine.item_id)
        ).all()
    )
    items = _items(s, set(on_hand))
    rows: list[dict[str, Any]] = []
    for item_id, (qty, value) in on_hand.items():
        it, unit = items[item_id]
        sold_qty = max(sold.get(item_id, ZERO), ZERO)
        daily = sold_qty / p.days
        cover = (qty / daily).quantize(Decimal(1)) if daily else None
        if cover is not None and cover <= p.cover_days:
            continue
        last: date | None = last_sale.get(item_id)
        rows.append(
            {
                "code": it.code,
                "name": it.name,
                "status": "راکد" if not sold_qty else "کم‌گردش",
                "qty": q(qty),
                "unit": unit,
                "value": m(value),
                "sold": q(sold_qty),
                "cover_days": int(cover) if cover is not None else None,
                "last_sale": last.isoformat() if last else None,
                "idle_days": (today - last).days if last else None,
            }
        )
    rows.sort(key=lambda r: Decimal(r["value"]), reverse=True)
    return ReportTable(
        key="slow-moving",
        title="کالاهای کم‌گردش و راکد",
        columns=[
            Column(key="code", label="کد"),
            Column(key="name", label="کالا"),
            Column(key="status", label="وضعیت"),
            Column(key="qty", label="موجودی", kind="qty"),
            Column(key="unit", label="واحد"),
            Column(key="value", label="ارزش موجودی", kind="money"),
            Column(key="sold", label=f"فروش {p.days} روز", kind="qty"),
            Column(key="cover_days", label="پوشش (روز)", kind="int"),
            Column(key="last_sale", label="آخرین فروش", kind="date"),
            Column(key="idle_days", label="روز بدون فروش", kind="int"),
        ],
        rows=page(rows, p.page, p.page_size),
        totals={"code": "جمع", "value": m(sum((Decimal(r["value"]) for r in rows), ZERO))},
        total_rows=len(rows),
        page=p.page,
        page_size=p.page_size,
        notes=[
            f"راکد: بدون فروش در {p.days} روز اخیر. کم‌گردش: موجودی با سرعت فروش اخیر "
            f"بیش از {p.cover_days} روز طول می‌کشد.",
        ],
    )


def near_expiry(s: Session, actor: Actor, p: ExpiryQ) -> ReportTable:
    """نزدیک انقضا. Stock is valued at moving average without lots, so which receipts are
    still on the shelf is estimated: the newest receipts are assumed to be what remains
    (first in, first out). Expired lines are listed too (negative days left)."""
    whs = _warehouses(s, actor, p.branch_id, p.warehouse_id)
    today = tehran_today()
    limit = today + timedelta(days=p.days)
    balances = list(
        s.execute(
            select(
                StockBalance.item_id,
                StockBalance.warehouse_id,
                StockBalance.qty,
                StockBalance.avg_cost,
            )
            .join(Item, Item.id == StockBalance.item_id)
            .where(
                StockBalance.warehouse_id.in_(whs),
                StockBalance.qty > 0,
                Item.track_expiry == true(),
            )
        )
    )
    items = _items(s, {b[0] for b in balances})
    wh_names = dict(s.execute(select(Warehouse.id, Warehouse.name)).all())
    rows: list[dict[str, Any]] = []
    for item_id, wh_id, qty, avg in balances:
        receipts = list(
            s.execute(
                select(StockLedger.qty_in, StockDocumentLine.expiry_date)
                .join(StockDocumentLine, StockDocumentLine.id == StockLedger.document_line_id)
                .where(
                    StockLedger.item_id == item_id,
                    StockLedger.warehouse_id == wh_id,
                    StockLedger.qty_in > 0,
                )
                .order_by(StockLedger.document_date.desc(), StockLedger.seq.desc())
            )
        )
        left = Decimal(qty)
        it, unit = items[item_id]
        for got, expiry in receipts:
            if left <= 0:
                break
            take = min(Decimal(got), left)
            left -= take
            if expiry is not None and expiry <= limit:
                rows.append(
                    {
                        "code": it.code,
                        "name": it.name,
                        "warehouse": wh_names.get(wh_id, ""),
                        "expiry": expiry.isoformat(),
                        "days_left": (expiry - today).days,
                        "qty": q(take),
                        "unit": unit,
                        "value": m(take * Decimal(avg)),
                    }
                )
    rows.sort(key=lambda r: r["expiry"])
    return ReportTable(
        key="near-expiry",
        title="کالاهای نزدیک انقضا",
        columns=[
            Column(key="code", label="کد"),
            Column(key="name", label="کالا"),
            Column(key="warehouse", label="انبار"),
            Column(key="expiry", label="تاریخ انقضا", kind="date"),
            Column(key="days_left", label="روز مانده", kind="int"),
            Column(key="qty", label="مقدار (برآوردی)", kind="qty"),
            Column(key="unit", label="واحد"),
            Column(key="value", label="ارزش (برآوردی)", kind="money"),
        ],
        rows=page(rows, p.page, p.page_size),
        totals={"code": "جمع", "value": m(sum((Decimal(r["value"]) for r in rows), ZERO))},
        total_rows=len(rows),
        page=p.page,
        page_size=p.page_size,
        notes=[
            f"کالاهای دارای تاریخ انقضا که تا {p.days} روز دیگر (یا پیش‌تر) منقضی می‌شوند.",
            "موجودی بچ‌به‌بچ نگهداری نمی‌شود؛ فرض شده جدیدترین ورودی‌ها هنوز در انبارند (FIFO).",
        ],
    )
