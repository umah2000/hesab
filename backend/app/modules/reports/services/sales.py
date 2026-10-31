"""Sales reports and the dashboard. Only final invoices; returns count negatively."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnClause, Date, case, func, literal, literal_column, select, text
from sqlalchemy.orm import Session

from app.core.db import load_columns_by_ids, utcnow
from app.modules.accounting.models import Voucher, VoucherLine
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.inventory.models import Item, ItemGroup, StockBalance, StockLot, Warehouse
from app.modules.inventory.services.stock import tehran_today
from app.modules.organization.models import Branch, CashRegister, Organization
from app.modules.parties.models import Party
from app.modules.reports.schemas import (
    Column,
    Dashboard,
    DashboardQ,
    DayPoint,
    ExpiryAlert,
    Kpi,
    ReportTable,
    SalesQ,
    ShortageQ,
    TopItem,
)
from app.modules.reports.services.common import (
    ZERO,
    branches,
    date_range,
    day_bounds,
    m,
    page,
    pct,
    q,
)
from app.modules.sales.models import (
    CashShift,
    SalesInvoice,
    SalesInvoiceLine,
    SalesPayment,
    TerminalTransaction,
)

# Constants are written into the SQL, not bound: as typed parameters inside these per-line
# CASE expressions they made SQL Server ~20x slower on 350k lines (phase 10 volume test).
# They are fixed code constants, never user input.
SALE: ColumnClause[str] = literal_column("'sale'")
RETURN: ColumnClause[str] = literal_column("'return'")
FINAL: ColumnClause[str] = literal_column("'final'")
SIGN = case((SalesInvoice.kind == RETURN, literal_column("-1")), else_=literal_column("1"))
MEASURES = (
    func.count(func.distinct(case((SalesInvoice.kind == SALE, SalesInvoice.id)))),
    func.count(func.distinct(case((SalesInvoice.kind == RETURN, SalesInvoice.id)))),
    func.sum(SIGN * SalesInvoiceLine.base_qty),
    func.sum(SIGN * (SalesInvoiceLine.promotion_discount + SalesInvoiceLine.manual_discount)),
    func.sum(SIGN * SalesInvoiceLine.revenue),
    func.sum(SIGN * SalesInvoiceLine.tax),
    func.sum(SIGN * SalesInvoiceLine.line_total),
    func.sum(SIGN * func.coalesce(SalesInvoiceLine.cost_total, literal_column("0"))),
)


def _lines(actor: Actor, branch_id: uuid.UUID | None, start: date, end: date):  # type: ignore[no-untyped-def]
    stmt = (
        select()
        .select_from(SalesInvoiceLine)
        .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
        .where(
            SalesInvoice.status == FINAL,
            SalesInvoice.document_date >= literal(start, Date, literal_execute=True),
            SalesInvoice.document_date <= literal(end, Date, literal_execute=True),
        )
    )
    scope = branches(actor, branch_id)
    if scope is not None:
        stmt = stmt.where(SalesInvoice.branch_id.in_(scope))
    return stmt


SALES_COLUMNS = [
    Column(key="invoices", label="فاکتور", kind="int"),
    Column(key="returns", label="برگشت", kind="int"),
    Column(key="qty", label="مقدار (واحد پایه)", kind="qty"),
    Column(key="discount", label="تخفیف", kind="money"),
    Column(key="net_sales", label="فروش خالص", kind="money"),
    Column(key="tax", label="مالیات", kind="money"),
    Column(key="total", label="جمع با مالیات", kind="money"),
    Column(key="cost", label="بهای تمام‌شده", kind="money"),
    Column(key="profit", label="سود ناخالص", kind="money"),
    Column(key="margin", label="حاشیه سود٪", kind="percent"),
]
GROUP_LABEL = {
    "day": "روز",
    "item": "کالا",
    "group": "گروه کالا",
    "cashier": "صندوق‌دار",
    "register": "صندوق",
    "branch": "شعبه",
}


def _values(r: Any) -> dict[str, Any]:
    invoices, returns, qty, disc, net, tax, total, cost = r
    net, cost = Decimal(net or 0), Decimal(cost or 0)
    return {
        "invoices": int(invoices or 0),
        "returns": int(returns or 0),
        "qty": q(qty),
        "discount": m(disc),
        "net_sales": m(net),
        "tax": m(tax),
        "total": m(total),
        "cost": m(cost),
        "profit": m(net - cost),
        "margin": pct(net - cost, net),
    }


def sales_report(s: Session, actor: Actor, p: SalesQ) -> ReportTable:
    start, end = date_range(p.date_from, p.date_to)
    base = _lines(actor, p.branch_id, start, end)
    key_cols: tuple[Any, ...] = {
        "day": (SalesInvoice.document_date,),
        "item": (SalesInvoiceLine.item_id,),
        "group": (Item.group_id,),
        "cashier": (SalesInvoice.created_by,),
        "register": (SalesInvoice.cash_register_id,),
        "branch": (SalesInvoice.branch_id,),
    }[p.group_by]
    stmt = base.add_columns(*key_cols, *MEASURES).group_by(*key_cols)
    if p.group_by == "group":
        stmt = stmt.join(Item, Item.id == SalesInvoiceLine.item_id)
    raw = list(s.execute(stmt))
    ids = {r[0] for r in raw if r[0] is not None}
    names: dict[Any, str] = {}
    if p.group_by == "item" and ids:
        names = {
            k: f"{r.code} — {r.name}"
            for k, r in load_columns_by_ids(s, Item.id, [Item.code, Item.name], ids).items()
        }
    elif p.group_by == "group" and ids:
        names = dict(
            s.execute(select(ItemGroup.id, ItemGroup.name).where(ItemGroup.id.in_(ids))).all()
        )
    elif p.group_by == "cashier" and ids:
        names = dict(
            s.execute(select(AppUser.id, AppUser.full_name).where(AppUser.id.in_(ids))).all()
        )
    elif p.group_by == "register" and ids:
        names = dict(
            s.execute(
                select(CashRegister.id, CashRegister.name).where(CashRegister.id.in_(ids))
            ).all()
        )
    elif p.group_by == "branch" and ids:
        names = dict(s.execute(select(Branch.id, Branch.name).where(Branch.id.in_(ids))).all())
    rows = []
    for r in raw:
        k = r[0]
        label = (
            k.isoformat()
            if p.group_by == "day"
            else names.get(k, "بدون گروه" if k is None else "—")
        )
        rows.append({"key": label, **_values(r[1:])})
    if p.group_by == "day":
        rows.sort(key=lambda x: x["key"])
    else:
        rows.sort(key=lambda x: Decimal(x["net_sales"]), reverse=True)
    totals = {"key": "جمع", **_values(s.execute(base.add_columns(*MEASURES)).one())}
    first = Column(
        key="key", label=GROUP_LABEL[p.group_by], kind="date" if p.group_by == "day" else "text"
    )
    return ReportTable(
        key="sales",
        title=f"فروش به تفکیک {GROUP_LABEL[p.group_by]}",
        columns=[first, *SALES_COLUMNS],
        rows=page(rows, p.page, p.page_size),
        totals=totals,
        total_rows=len(rows),
        page=p.page,
        page_size=p.page_size,
        notes=[
            f"از {start.isoformat()} تا {end.isoformat()}؛ فقط فاکتورهای قطعی. "
            "برگشت‌ها منفی حساب شده‌اند.",
            "فروش خالص بدون مالیات و پس از تخفیف است؛ "
            "سود ناخالص = فروش خالص − بهای تمام‌شده (میانگین موزون).",
        ],
    )


# --- cash shortages -----------------------------------------------------------------------


def cash_shortages(s: Session, actor: Actor, p: ShortageQ) -> ReportTable:
    start, end = date_range(p.date_from, p.date_to)
    lo, hi = day_bounds(start, end)
    stmt = select(CashShift).where(
        CashShift.status == "closed", CashShift.closed_at >= lo, CashShift.closed_at < hi
    )
    scope = branches(actor, p.branch_id)
    if scope is not None:
        stmt = stmt.where(CashShift.branch_id.in_(scope))
    shifts = list(s.scalars(stmt.order_by(CashShift.closed_at)))
    users = dict(s.execute(select(AppUser.id, AppUser.full_name)).all())
    regs = dict(s.execute(select(CashRegister.id, CashRegister.name)).all())
    groups: dict[Any, dict[str, Any]] = {}
    for sh in shifts:
        diff = sh.difference or ZERO
        if p.group_by == "shift":
            key: Any = sh.id
            label = f"{regs.get(sh.cash_register_id, '')} — {users.get(sh.user_id, '')}"
        elif p.group_by == "register":
            key, label = sh.cash_register_id, regs.get(sh.cash_register_id, "—")
        else:
            key, label = sh.user_id, users.get(sh.user_id, "—")
        g = groups.setdefault(
            key, {"key": label, "closed_at": None, "shifts": 0, "short": ZERO, "over": ZERO}
        )
        g["shifts"] += 1
        g["short"] += -diff if diff < 0 else ZERO
        g["over"] += diff if diff > 0 else ZERO
        g["closed_at"] = (
            sh.closed_at.astimezone(ZoneInfo("Asia/Tehran")).date().isoformat()
            if sh.closed_at
            else None
        )
    rows = [
        {
            "key": g["key"],
            "closed_at": g["closed_at"],
            "shifts": g["shifts"],
            "shortage": m(g["short"]),
            "overage": m(g["over"]),
            "net": m(g["over"] - g["short"]),
        }
        for g in groups.values()
    ]
    rows.sort(key=lambda r: Decimal(r["shortage"]), reverse=True)
    short = sum((g["short"] for g in groups.values()), ZERO)
    over = sum((g["over"] for g in groups.values()), ZERO)
    cols = [
        Column(
            key="key",
            label={"cashier": "صندوق‌دار", "register": "صندوق", "shift": "شیفت"}[p.group_by],
        ),
    ]
    if p.group_by == "shift":
        cols.append(Column(key="closed_at", label="تاریخ بستن", kind="date"))
    cols += [
        Column(key="shifts", label="شیفت", kind="int"),
        Column(key="shortage", label="کسری", kind="money"),
        Column(key="overage", label="اضافه", kind="money"),
        Column(key="net", label="خالص", kind="money"),
    ]
    return ReportTable(
        key="cash-shortages",
        title="کسری و اضافه صندوق",
        columns=cols,
        rows=page(rows, p.page, p.page_size),
        totals={
            "key": "جمع",
            "shifts": len(shifts),
            "shortage": m(short),
            "overage": m(over),
            "net": m(over - short),
        },
        total_rows=len(rows),
        page=p.page,
        page_size=p.page_size,
        notes=["شیفت‌های بسته‌شده در بازه؛ شمارش کور در پایان شیفت (فاز ۴)."],
    )


# --- dashboard ------------------------------------------------------------------------------


def _kpi(s: Session, actor: Actor, branch_id: uuid.UUID | None, start: date, end: date) -> Kpi:
    r = s.execute(_lines(actor, branch_id, start, end).add_columns(*MEASURES)).one()
    invoices, returns = int(r[0] or 0), int(r[1] or 0)
    net, cost = Decimal(r[4] or 0), Decimal(r[7] or 0)
    total = Decimal(r[6] or 0)
    return Kpi(
        net_sales=m(net),
        gross_profit=m(net - cost),
        margin=pct(net - cost, net),
        invoices=invoices,
        returns=returns,
        average_basket=m(total / invoices) if invoices else None,
    )


def dashboard(s: Session, actor: Actor, p: DashboardQ) -> Dashboard:
    start, end = date_range(p.date_from, p.date_to, default_days=1)
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    base = _lines(actor, p.branch_id, start, end)

    series = []
    by_day = {
        r[0]: r[1:]
        for r in s.execute(
            base.add_columns(SalesInvoice.document_date, *MEASURES).group_by(
                SalesInvoice.document_date
            )
        )
    }
    if span <= 92:
        d = start
        while d <= end:
            r = by_day.get(d)
            net = Decimal(r[4] or 0) if r else ZERO
            cost = Decimal(r[7] or 0) if r else ZERO
            series.append(
                DayPoint(
                    date=d,
                    net_sales=m(net),
                    gross_profit=m(net - cost),
                    invoices=int(r[0] or 0) if r else 0,
                )
            )
            d += timedelta(days=1)

    top = list(
        s.execute(
            base.add_columns(SalesInvoiceLine.item_id, *MEASURES)
            .group_by(SalesInvoiceLine.item_id)
            .order_by(func.sum(SIGN * SalesInvoiceLine.revenue).desc())
            .limit(10)
        )
    )
    items = (
        {i.id: i for i in s.scalars(select(Item).where(Item.id.in_({r[0] for r in top})))}
        if top
        else {}
    )
    top_items = [
        TopItem(
            item_id=r[0],
            code=items[r[0]].code,
            name=items[r[0]].name,
            qty=q(r[3]),
            net_sales=m(r[5]),
        )
        for r in top
        if r[0] in items
    ]

    pay_stmt = (
        select(SalesPayment.method, func.sum(SIGN * SalesPayment.amount))
        .join(SalesInvoice, SalesInvoice.id == SalesPayment.invoice_id)
        .where(
            SalesInvoice.status == "final",
            SalesInvoice.document_date >= start,
            SalesInvoice.document_date <= end,
        )
        .group_by(SalesPayment.method)
    )
    scope = branches(actor, p.branch_id)
    if scope is not None:
        pay_stmt = pay_stmt.where(SalesInvoice.branch_id.in_(scope))
    payments = {k: m(v) for k, v in s.execute(pay_stmt)}

    inventory_value = below_min = None
    if actor.has("inventory.report.view"):
        inv_stmt = select(func.sum(StockBalance.value)).join(
            Warehouse, Warehouse.id == StockBalance.warehouse_id
        )
        if scope is not None:
            inv_stmt = inv_stmt.where(Warehouse.branch_id.in_(scope))
        inventory_value = m(s.scalar(inv_stmt))
        per_item = (
            select(StockBalance.item_id, func.sum(StockBalance.qty).label("qty"))
            .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
            .group_by(StockBalance.item_id)
        )
        if scope is not None:
            per_item = per_item.where(Warehouse.branch_id.in_(scope))
        sub = per_item.subquery()
        below_min = int(
            s.scalar(
                select(func.count())
                .select_from(Item)
                .outerjoin(sub, sub.c.item_id == Item.id)
                .where(Item.min_qty.is_not(None), func.coalesce(sub.c.qty, 0) < Item.min_qty)
            )
            or 0
        )

    expiry = _expiry_alert(s, scope) if actor.has("inventory.report.view") else None

    receivables = payables = None
    if actor.has("parties.view") or actor.has("parties.manage"):
        bal = (
            select(
                VoucherLine.detail_account_id.label("pid"),
                func.sum(VoucherLine.debit - VoucherLine.credit).label("b"),
            )
            .join(Voucher, Voucher.id == VoucherLine.voucher_id)
            .join(Party, Party.id == VoucherLine.detail_account_id)
            .where(Voucher.status == "final")
            .group_by(VoucherLine.detail_account_id)
            .subquery()
        )
        rec, pay = s.execute(
            select(
                func.sum(case((bal.c.b > 0, bal.c.b), else_=0)),
                func.sum(case((bal.c.b < 0, -bal.c.b), else_=0)),
            )
        ).one()
        receivables, payables = m(rec), m(pay)

    short_stmt = select(
        func.sum(case((CashShift.difference < 0, -CashShift.difference), else_=0))
    ).where(
        CashShift.status == "closed",
        CashShift.closed_at >= day_bounds(start, end)[0],
        CashShift.closed_at < day_bounds(start, end)[1],
    )
    unknown_stmt = (
        select(func.count())
        .select_from(TerminalTransaction)
        .where(TerminalTransaction.status.in_(("Unknown", "ReconciliationRequired")))
    )
    if scope is not None:
        short_stmt = short_stmt.where(CashShift.branch_id.in_(scope))
        unknown_stmt = unknown_stmt.join(
            CashRegister, CashRegister.id == TerminalTransaction.cash_register_id
        ).where(CashRegister.branch_id.in_(scope))
    return Dashboard(
        date_from=start,
        date_to=end,
        current=_kpi(s, actor, p.branch_id, start, end),
        previous=_kpi(s, actor, p.branch_id, prev_start, prev_end),
        series=series,
        top_items=top_items,
        payments=payments,
        inventory_value=inventory_value,
        below_min_items=below_min,
        expiry=expiry,
        receivables=receivables,
        payables=payables,
        cash_shortage=m(s.scalar(short_stmt)),
        unknown_card_transactions=int(s.scalar(unknown_stmt) or 0),
        generated_at=utcnow(),
    )


def _expiry_alert(s: Session, scope: set[uuid.UUID] | None) -> ExpiryAlert:
    """How many lots have expired, expire within the urgent days, or within the warning
    days (each lot counted once, in the nearest band)."""
    org = s.scalar(select(Organization))
    warn = org.expiry_warn_days if org else 30
    urgent = org.expiry_urgent_days if org else 7
    today = tehran_today()
    left = func.datediff(text("day"), today, StockLot.expiry_date)
    stmt = select(
        func.sum(case((left < 0, 1), else_=0)),
        func.sum(case(((left >= 0) & (left <= urgent), 1), else_=0)),
        func.sum(case(((left > urgent) & (left <= warn), 1), else_=0)),
    ).where(StockLot.qty > 0, StockLot.expiry_date.is_not(None))
    if scope is not None:
        stmt = stmt.join(Warehouse, Warehouse.id == StockLot.warehouse_id).where(
            Warehouse.branch_id.in_(scope)
        )
    expired, near, soon = s.execute(stmt).one()
    return ExpiryAlert(
        expired=int(expired or 0),
        urgent=int(near or 0),
        soon=int(soon or 0),
        urgent_days=urgent,
        warn_days=warn,
    )
