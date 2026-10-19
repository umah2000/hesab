"""Visitor performance (ADR-0018): visits, orders and what became sales."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.distribution.models import SalesOrder, Visit, Visitor
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.reports.schemas import Column, RangeQ, ReportTable
from app.modules.reports.services.common import (
    branches,
    date_range,
    day_bounds,
    m,
    page,
    pct,
)

ZERO = Decimal(0)
SOLD = ("invoiced", "delivered")


def visitor_performance(s: Session, actor: Actor, p: RangeQ) -> ReportTable:
    start, end = date_range(p.date_from, p.date_to)
    lo, hi = day_bounds(start, end)
    vq = select(Visitor)
    scope = branches(actor, p.branch_id)
    if scope is not None:
        vq = vq.where(Visitor.branch_id.in_(scope))
    vis = list(s.scalars(vq))
    names = dict(s.execute(select(AppUser.id, AppUser.full_name)).all())
    ids = [v.id for v in vis] or [uuid.UUID(int=0)]
    rows_by: dict[Any, dict[str, Any]] = {
        v.id: {
            "visitor": f"{names.get(v.user_id, '')} ({v.code})",
            "visits": 0,
            "productive": 0,
            "orders": 0,
            "ordered": ZERO,
            "sold": ZERO,
            "delivered": 0,
            "lost": 0,
        }
        for v in vis
    }
    for visit in s.scalars(
        select(Visit).where(
            Visit.visitor_id.in_(ids), Visit.visited_at >= lo, Visit.visited_at < hi
        )
    ):
        r = rows_by[visit.visitor_id]
        r["visits"] += 1
        r["productive"] += 1 if visit.outcome == "order" else 0
    for o in s.scalars(
        select(SalesOrder).where(
            SalesOrder.visitor_id.in_(ids),
            SalesOrder.ordered_at >= lo,
            SalesOrder.ordered_at < hi,
        )
    ):
        r = rows_by[o.visitor_id]
        if o.status == "cancelled":
            continue
        r["orders"] += 1
        r["ordered"] += o.grand_total
        if o.status in SOLD:
            r["sold"] += o.grand_total
        r["delivered"] += 1 if o.status == "delivered" else 0
        r["lost"] += 1 if o.status == "rejected" else 0
    rows = [
        {
            "visitor": r["visitor"],
            "visits": r["visits"],
            "productive": r["productive"],
            "hit_rate": pct(Decimal(r["productive"]), Decimal(r["visits"])),
            "orders": r["orders"],
            "ordered": m(r["ordered"]),
            "sold": m(r["sold"]),
            "delivered": r["delivered"],
            "rejected": r["lost"],
        }
        for r in rows_by.values()
    ]
    rows.sort(key=lambda r: Decimal(r["sold"]), reverse=True)
    tot = list(rows_by.values())
    visits = sum(r["visits"] for r in tot)
    productive = sum(r["productive"] for r in tot)
    return ReportTable(
        key="visitor-performance",
        title="عملکرد ویزیتورها",
        columns=[
            Column(key="visitor", label="ویزیتور"),
            Column(key="visits", label="بازدید", kind="int"),
            Column(key="productive", label="بازدید با سفارش", kind="int"),
            Column(key="hit_rate", label="نرخ موفقیت", kind="percent"),
            Column(key="orders", label="سفارش", kind="int"),
            Column(key="ordered", label="مبلغ سفارش", kind="money"),
            Column(key="sold", label="فاکتورشده", kind="money"),
            Column(key="delivered", label="تحویل‌شده", kind="int"),
            Column(key="rejected", label="ردشده", kind="int"),
        ],
        rows=page(rows, p.page, p.page_size),
        totals={
            "visitor": "جمع",
            "visits": visits,
            "productive": productive,
            "hit_rate": pct(Decimal(productive), Decimal(visits)),
            "orders": sum(r["orders"] for r in tot),
            "ordered": m(sum((r["ordered"] for r in tot), ZERO)),
            "sold": m(sum((r["sold"] for r in tot), ZERO)),
            "delivered": sum(r["delivered"] for r in tot),
            "rejected": sum(r["lost"] for r in tot),
        },
        total_rows=len(rows),
        page=p.page,
        page_size=p.page_size,
        notes=[
            "سفارش‌ها بر اساس زمان ثبت روی گوشی؛ سفارش لغوشده توسط ویزیتور شمرده نمی‌شود.",
            "«فاکتورشده» مبلغ سفارش‌هایی است که به فاکتور فروش تبدیل شده‌اند "
            "(پس از تخفیف و با مالیات).",
        ],
    )
