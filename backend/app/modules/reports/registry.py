"""Every report: who may run it, its filters and its function (ADR-0016)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.modules.iam.guard import Actor
from app.modules.reports.schemas import (
    AgingQ,
    BalanceSheetQ,
    ExpiryQ,
    RangeQ,
    ReportInfo,
    ReportTable,
    SalesQ,
    ShortageQ,
    SlowQ,
    StatementQ,
    StockMovementQ,
)
from app.modules.reports.services import distribution, finance, inventory, sales


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    description: str
    group: str
    permissions: tuple[str, ...]
    query: type[BaseModel]
    run: Callable[[Session, Actor, Any], ReportTable]
    filters: tuple[str, ...]


REPORTS: dict[str, Report] = {
    r.key: r
    for r in (
        Report(
            "sales",
            "فروش",
            "فروش خالص، تخفیف، مالیات، بهای تمام‌شده و سود به تفکیک روز، کالا، گروه، "
            "صندوق‌دار، صندوق یا شعبه",
            "فروش",
            ("sales.report.view",),
            SalesQ,
            sales.sales_report,
            ("date_from", "date_to", "branch_id", "group_by"),
        ),
        Report(
            "visitor-performance",
            "عملکرد ویزیتورها",
            "بازدید، نرخ موفقیت، سفارش، فاکتورشده و تحویل‌شده به تفکیک ویزیتور",
            "ویزیتور و توزیع",
            ("distribution.manage",),
            RangeQ,
            distribution.visitor_performance,
            ("date_from", "date_to", "branch_id"),
        ),
        Report(
            "cash-shortages",
            "کسری و اضافه صندوق",
            "نتیجه شمارش پایان شیفت به تفکیک صندوق‌دار، صندوق یا شیفت",
            "فروش",
            ("sales.report.view",),
            ShortageQ,
            sales.cash_shortages,
            ("date_from", "date_to", "branch_id", "group_by"),
        ),
        Report(
            "stock-movement",
            "گردش کالا",
            "موجودی اول دوره، ورود، خروج و پایان دوره هر کالا با ارزش",
            "انبار",
            ("inventory.report.view",),
            StockMovementQ,
            inventory.stock_movement,
            ("date_from", "date_to", "branch_id", "warehouse_id", "q", "only_moved"),
        ),
        Report(
            "slow-moving",
            "کالاهای کم‌گردش و راکد",
            "کالاهای دارای موجودی که فروش نداشته‌اند یا موجودی آن‌ها بیش از حد است",
            "انبار",
            ("inventory.report.view",),
            SlowQ,
            inventory.slow_moving,
            ("branch_id", "warehouse_id", "days", "cover_days"),
        ),
        Report(
            "near-expiry",
            "کالاهای نزدیک انقضا",
            "برآورد مقدار در انبار با تاریخ انقضای نزدیک یا گذشته",
            "انبار",
            ("inventory.report.view",),
            ExpiryQ,
            inventory.near_expiry,
            ("branch_id", "warehouse_id", "days"),
        ),
        Report(
            "debtors",
            "بدهکاران",
            "طلب از طرف‌حساب‌ها با سن بدهی",
            "طرف‌حساب",
            ("parties.view", "parties.manage"),
            AgingQ,
            lambda s, a, q: finance.aging(s, a, q.model_copy(update={"side": "debtors"})),
            ("as_of",),
        ),
        Report(
            "creditors",
            "بستانکاران",
            "بدهی به طرف‌حساب‌ها با سن بدهی",
            "طرف‌حساب",
            ("parties.view", "parties.manage"),
            AgingQ,
            lambda s, a, q: finance.aging(s, a, q.model_copy(update={"side": "creditors"})),
            ("as_of",),
        ),
        Report(
            "money-flow",
            "گردش صندوق و بانک",
            "مانده اول، دریافت، پرداخت و مانده پایان هر صندوق و حساب بانکی",
            "خزانه",
            ("treasury.manage",),
            RangeQ,
            finance.money_flow,
            ("date_from", "date_to", "branch_id"),
        ),
        Report(
            "profit-loss",
            "سود و زیان",
            "درآمد، بهای تمام‌شده، سود ناخالص، هزینه‌ها و سود خالص در سال مالی",
            "مالی",
            ("accounting.report.view",),
            StatementQ,
            finance.profit_loss,
            ("date_from", "date_to", "branch_id"),
        ),
        Report(
            "balance-sheet",
            "ترازنامه",
            "دارایی‌ها، بدهی‌ها و حقوق مالکانه در یک تاریخ",
            "مالی",
            ("accounting.report.view",),
            BalanceSheetQ,
            finance.balance_sheet,
            ("as_of", "branch_id"),
        ),
    )
}

ALL_PERMISSIONS = tuple(sorted({p for r in REPORTS.values() for p in r.permissions}))


def allowed(actor: Actor, report: Report) -> bool:
    return any(actor.has(p) for p in report.permissions)


def catalog(actor: Actor) -> list[ReportInfo]:
    return [
        ReportInfo(
            key=r.key,
            title=r.title,
            description=r.description,
            group=r.group,
            filters=list(r.filters),
        )
        for r in REPORTS.values()
        if allowed(actor, r)
    ]
