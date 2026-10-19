"""Financial reports — only final vouchers (MASTER_PROMPT §5 module 9)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.db import load_by_ids
from app.core.errors import DomainError
from app.modules.accounting.models import Account, DetailAccount, FiscalYear, Voucher, VoucherLine
from app.modules.accounting.services.fiscal import get_year
from app.modules.iam.guard import Actor
from app.modules.inventory.services.stock import tehran_today
from app.modules.parties.models import Party
from app.modules.reports.schemas import (
    AgingQ,
    BalanceSheetQ,
    Column,
    RangeQ,
    ReportTable,
    StatementQ,
)
from app.modules.reports.services.common import ZERO, branches, date_range, m, page
from app.modules.treasury.models import MoneyAccount

BUCKETS = ((30, "b0"), (60, "b31"), (90, "b61"), (None, "b91"))


def _final(actor: Actor, branch_id: uuid.UUID | None):  # type: ignore[no-untyped-def]
    stmt = (
        select()
        .select_from(VoucherLine)
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(Voucher.status == "final")
    )
    scope = branches(actor, branch_id)
    if scope is not None:
        stmt = stmt.where(Voucher.branch_id.in_(scope))
    return stmt


# --- debtors / creditors with aging ----------------------------------------------------------


def aging(s: Session, actor: Actor, p: AgingQ) -> ReportTable:
    """Balance per party, split by age: payments are assumed to settle the oldest
    entries first, so what is still open are the most recent ones."""
    as_of = p.as_of or tehran_today()
    debtors = p.side == "debtors"
    lines = list(
        s.execute(
            _final(actor, None)
            .add_columns(
                VoucherLine.detail_account_id,
                Voucher.document_date,
                VoucherLine.debit,
                VoucherLine.credit,
            )
            .join(Party, Party.id == VoucherLine.detail_account_id)
            .where(Voucher.document_date <= as_of)
        )
    )
    by_party: dict[uuid.UUID, list[tuple[date, Decimal]]] = defaultdict(list)
    for pid, d, dr, cr in lines:
        by_party[pid].append((d, Decimal(dr) - Decimal(cr)))
    names = {k: (d.code, d.name) for k, d in load_by_ids(s, DetailAccount, by_party).items()}
    rows = []
    totals: defaultdict[str, Decimal] = defaultdict(lambda: ZERO)
    for pid, entries in by_party.items():
        bal = sum((a for _, a in entries), ZERO)
        open_amt = bal if debtors else -bal
        if open_amt <= 0:
            continue
        buckets = dict.fromkeys(("b0", "b31", "b61", "b91"), ZERO)
        left = open_amt
        # Newest increases first: debits for a debtor, credits for a creditor.
        for d, amt in sorted(entries, key=lambda e: e[0], reverse=True):
            inc = amt if debtors else -amt
            if inc <= 0 or left <= 0:
                continue
            take = min(inc, left)
            left -= take
            age = (as_of - d).days
            key = next(k for lim, k in BUCKETS if lim is None or age <= lim)
            buckets[key] += take
        if left > 0:  # opening balances without dated increases
            buckets["b91"] += left
        code, name = names.get(pid, ("", ""))
        rows.append(
            {
                "code": code,
                "name": name,
                "balance": m(open_amt),
                **{k: m(v) for k, v in buckets.items()},
            }
        )
        totals["balance"] += open_amt
        for k, v in buckets.items():
            totals[k] += v
    rows.sort(key=lambda r: Decimal(r["balance"]), reverse=True)
    title = "بدهکاران (طلب ما)" if debtors else "بستانکاران (بدهی ما)"
    return ReportTable(
        key="debtors" if debtors else "creditors",
        title=title,
        columns=[
            Column(key="code", label="کد"),
            Column(key="name", label="طرف‌حساب"),
            Column(key="balance", label="مانده", kind="money"),
            Column(key="b0", label="تا ۳۰ روز", kind="money"),
            Column(key="b31", label="۳۱ تا ۶۰", kind="money"),
            Column(key="b61", label="۶۱ تا ۹۰", kind="money"),
            Column(key="b91", label="بیش از ۹۰ روز", kind="money"),
        ],
        rows=page(rows, p.page, p.page_size),
        totals={"code": "جمع", **{k: m(v) for k, v in totals.items()}},
        total_rows=len(rows),
        page=p.page,
        page_size=p.page_size,
        notes=[
            f"مانده تا {as_of.isoformat()} از همه اسناد قطعی "
            "(شامل اسناد دریافتنی/پرداختنی و چک در جریان).",
            "سن بدهی با فرض تسویه قدیمی‌ترین بدهی‌ها محاسبه شده است.",
        ],
    )


# --- cash and bank movement ---------------------------------------------------------------


def money_flow(s: Session, actor: Actor, p: RangeQ) -> ReportTable:
    start, end = date_range(p.date_from, p.date_to)
    accounts = {
        ma.id: (ma, d)
        for ma, d in s.execute(
            select(MoneyAccount, DetailAccount).join(
                DetailAccount, DetailAccount.id == MoneyAccount.id
            )
        )
        if ma.branch_id is None or actor.can_access_branch(ma.branch_id)
    }
    if p.branch_id is not None:
        accounts = {k: v for k, v in accounts.items() if v[0].branch_id in (None, p.branch_id)}
    before = Voucher.document_date < start
    raw = {
        r[0]: [Decimal(x or 0) for x in r[1:]]
        for r in s.execute(
            _final(actor, None)
            .add_columns(
                VoucherLine.detail_account_id,
                func.sum(case((before, VoucherLine.debit - VoucherLine.credit), else_=0)),
                func.sum(case((before, 0), else_=VoucherLine.debit)),
                func.sum(case((before, 0), else_=VoucherLine.credit)),
            )
            .where(
                VoucherLine.detail_account_id.in_(set(accounts) or {uuid.UUID(int=0)}),
                Voucher.document_date <= end,
            )
            .group_by(VoucherLine.detail_account_id)
        )
    }
    rows, tot = [], [ZERO] * 3
    for aid, (ma, d) in sorted(accounts.items(), key=lambda x: (x[1][0].kind, x[1][1].code)):
        o, i, x = raw.get(aid, [ZERO] * 3)
        rows.append(
            {
                "code": d.code,
                "name": d.name,
                "kind": "صندوق" if ma.kind == "cash" else "بانک",
                "opening": m(o),
                "in": m(i),
                "out": m(x),
                "closing": m(o + i - x),
            }
        )
        tot = [tot[0] + o, tot[1] + i, tot[2] + x]
    return ReportTable(
        key="money-flow",
        title="گردش صندوق و بانک",
        columns=[
            Column(key="code", label="کد"),
            Column(key="name", label="حساب"),
            Column(key="kind", label="نوع"),
            Column(key="opening", label="مانده اول دوره", kind="money"),
            Column(key="in", label="ورود (دریافت)", kind="money"),
            Column(key="out", label="خروج (پرداخت)", kind="money"),
            Column(key="closing", label="مانده پایان دوره", kind="money"),
        ],
        rows=page(rows, p.page, p.page_size),
        totals={
            "code": "جمع",
            "opening": m(tot[0]),
            "in": m(tot[1]),
            "out": m(tot[2]),
            "closing": m(tot[0] + tot[1] - tot[2]),
        },
        total_rows=len(rows),
        page=p.page,
        page_size=p.page_size,
        notes=[f"از {start.isoformat()} تا {end.isoformat()}؛ فقط اسناد قطعی."],
    )


# --- statements -------------------------------------------------------------------------


def _account_sums(
    s: Session,
    actor: Actor,
    branch_id: uuid.UUID | None,
    fy: FiscalYear,
    start: date,
    end: date,
    categories: tuple[str, ...],
    include_closing: bool,
) -> tuple[dict[uuid.UUID, Decimal], dict[uuid.UUID, Account]]:
    """Debit − credit per posting account within [start, end] of one fiscal year."""
    stmt = (
        _final(actor, branch_id)
        .add_columns(VoucherLine.account_id, func.sum(VoucherLine.debit - VoucherLine.credit))
        .join(Account, Account.id == VoucherLine.account_id)
        .where(
            Voucher.fiscal_year_id == fy.id,
            Voucher.document_date >= start,
            Voucher.document_date <= end,
            Account.category.in_(categories),
        )
        .group_by(VoucherLine.account_id)
    )
    if not include_closing:
        stmt = stmt.where(Voucher.source_type != "closing")
    sums = {k: Decimal(v or 0) for k, v in s.execute(stmt)}
    return sums, {a.id: a for a in s.scalars(select(Account))}


def _tree_rows(
    sums: dict[uuid.UUID, Decimal], accounts: dict[uuid.UUID, Account], root_code: str, sign: int
) -> tuple[list[dict[str, Any]], Decimal]:
    """General (کل) and subsidiary (معین) rows under one group account, signed so that the
    group's natural side is positive."""
    by_parent: dict[uuid.UUID | None, list[Account]] = defaultdict(list)
    for a in accounts.values():
        by_parent[a.parent_id].append(a)
    root = next((a for a in accounts.values() if a.code == root_code), None)
    if root is None:
        return [], ZERO

    def total(a: Account) -> Decimal:
        return sums.get(a.id, ZERO) + sum((total(c) for c in by_parent[a.id]), ZERO)

    rows: list[dict[str, Any]] = []
    for general in sorted(by_parent[root.id], key=lambda x: x.code):
        g = total(general) * sign
        if not g and not any(total(c) for c in by_parent[general.id]):
            continue
        rows.append({"code": general.code, "name": general.name, "amount": m(g), "_level": 1})
        for sub in sorted(by_parent[general.id], key=lambda x: x.code):
            v = total(sub) * sign
            if v:
                rows.append({"code": sub.code, "name": sub.name, "amount": m(v), "_level": 2})
    return rows, total(root) * sign


def _year(s: Session, fiscal_year_id: uuid.UUID | None, on: date) -> FiscalYear:
    if fiscal_year_id is not None:
        return get_year(s, fiscal_year_id)
    fy = s.scalar(select(FiscalYear).where(FiscalYear.start_date <= on, FiscalYear.end_date >= on))
    if fy is None:
        raise DomainError("برای این تاریخ سال مالی تعریف نشده است", code="no_fiscal_year")
    return fy


def profit_loss(s: Session, actor: Actor, p: StatementQ) -> ReportTable:
    fy = _year(s, p.fiscal_year_id, p.date_to or tehran_today())
    start, end = p.date_from or fy.start_date, p.date_to or min(fy.end_date, tehran_today())
    if start < fy.start_date or end > fy.end_date or start > end:
        raise DomainError("بازه تاریخ باید داخل سال مالی باشد", code="invalid_range")
    sums, accounts = _account_sums(
        s, actor, p.branch_id, fy, start, end, ("revenue", "expense"), False
    )

    rows: list[dict[str, Any]] = []

    def section(code: str, title: str, sign: int) -> Decimal:
        body, amount = _tree_rows(sums, accounts, code, sign)
        rows.append({"code": code, "name": title, "amount": m(amount), "_level": 0, "_bold": True})
        rows.extend(body)
        return amount

    revenue = section("5", "درآمدها", -1)
    cogs = section("6", "بهای تمام‌شده", 1)
    rows.append(
        {"code": "", "name": "سود ناخالص", "amount": m(revenue - cogs), "_level": 0, "_bold": True}
    )
    expenses = section("7", "هزینه‌ها", 1)
    net = revenue - cogs - expenses
    rows.append(
        {
            "code": "",
            "name": "سود (زیان) خالص" if net >= 0 else "زیان خالص",
            "amount": m(net),
            "_level": 0,
            "_bold": True,
        }
    )
    return ReportTable(
        key="profit-loss",
        title="صورت سود و زیان",
        columns=[
            Column(key="code", label="کد"),
            Column(key="name", label="شرح"),
            Column(key="amount", label="مبلغ", kind="money"),
        ],
        rows=rows,
        totals=None,
        total_rows=len(rows),
        page=1,
        page_size=len(rows),
        notes=[
            f"سال مالی {fy.title}، از {start.isoformat()} تا {end.isoformat()}؛ "
            "فقط اسناد قطعی، بدون سند بستن حساب‌ها.",
            "برگشت و تخفیف فروش در گروه درآمد با علامت منفی آمده‌اند.",
        ],
    )


def balance_sheet(s: Session, actor: Actor, p: BalanceSheetQ) -> ReportTable:
    as_of = p.as_of or tehran_today()
    fy = _year(s, None, as_of)
    sums, accounts = _account_sums(
        s,
        actor,
        p.branch_id,
        fy,
        fy.start_date,
        as_of,
        ("asset", "liability", "equity", "revenue", "expense"),
        True,
    )
    rows: list[dict[str, Any]] = []

    def block(codes: tuple[str, ...], title: str, sign: int) -> Decimal:
        total = ZERO
        rows.append({"code": "", "name": title, "amount": None, "_level": 0, "_bold": True})
        for code in codes:
            body, amount = _tree_rows(sums, accounts, code, sign)
            root = next((a for a in accounts.values() if a.code == code), None)
            if root is None:
                continue
            rows.append(
                {"code": code, "name": root.name, "amount": m(amount), "_level": 1, "_bold": True}
            )
            rows.extend({**r, "_level": r["_level"] + 1} for r in body)
            total += amount
        rows.append(
            {"code": "", "name": f"جمع {title}", "amount": m(total), "_level": 0, "_bold": True}
        )
        return total

    assets = block(("1", "2"), "دارایی‌ها", 1)
    liabilities = block(("3",), "بدهی‌ها", -1)
    equity = block(("4",), "حقوق مالکانه", -1)
    # Profit not yet closed into retained earnings belongs to equity.
    pl = -sum((v for k, v in sums.items() if accounts[k].category in ("revenue", "expense")), ZERO)
    rows.append({"code": "", "name": "سود (زیان) دوره جاری", "amount": m(pl), "_level": 1})
    right = liabilities + equity + pl
    rows.append(
        {
            "code": "",
            "name": "جمع بدهی‌ها و حقوق مالکانه",
            "amount": m(right),
            "_level": 0,
            "_bold": True,
        }
    )
    notes = [f"تا تاریخ {as_of.isoformat()} (سال مالی {fy.title})؛ فقط اسناد قطعی."]
    if assets != right:
        notes.append(
            f"⚠ ترازنامه تراز نیست (اختلاف {m(assets - right)} ریال)؛ اسناد را بررسی کنید."
        )
    return ReportTable(
        key="balance-sheet",
        title="ترازنامه",
        columns=[
            Column(key="code", label="کد"),
            Column(key="name", label="شرح"),
            Column(key="amount", label="مبلغ", kind="money"),
        ],
        rows=rows,
        totals=None,
        total_rows=len(rows),
        page=1,
        page_size=len(rows),
        notes=notes,
    )
