"""Financial reports. Only final vouchers count (MASTER_PROMPT §5 module 9)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, NotFoundError
from app.core.http import Page
from app.core.money import ZERO
from app.modules.accounting.models import Account, DetailAccount, Voucher, VoucherLine
from app.modules.accounting.schemas import (
    LedgerOut,
    LedgerQuery,
    LedgerRow,
    TrialBalanceOut,
    TrialBalanceQuery,
    TrialBalanceRow,
    VoucherOut,
)
from app.modules.accounting.services.fiscal import get_year
from app.modules.accounting.services.vouchers import voucher_out
from app.modules.iam.guard import Actor

_LEVEL_DEPTH = {"group": 0, "general": 1, "subsidiary": 2}


def _scope(stmt: Select, actor: Actor) -> Select:  # type: ignore[type-arg]
    if actor.branch_ids is not None:
        stmt = stmt.where(Voucher.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    return stmt


def _range(
    fy_start: date, fy_end: date, d_from: date | None, d_to: date | None
) -> tuple[date, date]:
    start, end = d_from or fy_start, d_to or fy_end
    if start < fy_start or end > fy_end or start > end:
        raise DomainError("بازه تاریخ باید داخل سال مالی باشد", code="invalid_range")
    return start, end


def trial_balance(s: Session, actor: Actor, q: TrialBalanceQuery) -> TrialBalanceOut:
    fy = get_year(s, q.fiscal_year_id)
    start, end = _range(fy.start_date, fy.end_date, q.date_from, q.date_to)
    is_opening = Voucher.document_date < start
    stmt = (
        select(
            VoucherLine.account_id,
            func.sum(func.iif(is_opening, VoucherLine.debit, 0)),
            func.sum(func.iif(is_opening, VoucherLine.credit, 0)),
            func.sum(func.iif(is_opening, 0, VoucherLine.debit)),
            func.sum(func.iif(is_opening, 0, VoucherLine.credit)),
        )
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(
            Voucher.fiscal_year_id == fy.id, Voucher.status == "final", Voucher.document_date <= end
        )
        .group_by(VoucherLine.account_id)
    )
    if not q.include_closing:
        stmt = stmt.where(Voucher.source_type != "closing")
    sums = {r[0]: [Decimal(x or 0) for x in r[1:]] for r in s.execute(_scope(stmt, actor))}

    accounts = {a.id: a for a in s.scalars(select(Account))}
    target_depth = _LEVEL_DEPTH[q.level]
    agg: dict[uuid.UUID, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO, ZERO])
    for acc_id, vals in sums.items():
        a = accounts[acc_id]
        while _LEVEL_DEPTH[a.level] > target_depth and a.parent_id is not None:
            a = accounts[a.parent_id]
        row = agg[a.id]
        for i in range(4):
            row[i] += vals[i]

    def make(
        a_id: uuid.UUID | None, code: str, name: str, level: str, v: list[Decimal]
    ) -> TrialBalanceRow:
        opening = v[0] - v[1]
        closing = opening + v[2] - v[3]
        return TrialBalanceRow(
            account_id=a_id or uuid.UUID(int=0),
            code=code,
            name=name,
            level=level,  # type: ignore[arg-type]
            opening_debit=max(opening, ZERO),
            opening_credit=max(-opening, ZERO),
            turnover_debit=v[2],
            turnover_credit=v[3],
            balance_debit=max(closing, ZERO),
            balance_credit=max(-closing, ZERO),
        )

    rows = []
    source = accounts.values() if q.include_zero else [accounts[i] for i in agg]
    for a in sorted(source, key=lambda x: x.code):
        if _LEVEL_DEPTH[a.level] != target_depth:
            continue
        rows.append(make(a.id, a.code, a.name, a.level, agg.get(a.id, [ZERO] * 4)))

    totals = make(None, "", "جمع کل", q.level, [ZERO] * 4)
    for f in (
        "opening_debit",
        "opening_credit",
        "turnover_debit",
        "turnover_credit",
        "balance_debit",
        "balance_credit",
    ):
        setattr(totals, f, sum((getattr(r, f) for r in rows), ZERO))
    balanced = (
        totals.turnover_debit == totals.turnover_credit
        and totals.balance_debit == totals.balance_credit
        and totals.opening_debit == totals.opening_credit
    )
    return TrialBalanceOut(rows=rows, totals=totals, is_balanced=balanced)


def _descendants(accounts: dict[uuid.UUID, Account], root: uuid.UUID) -> set[uuid.UUID]:
    children: dict[uuid.UUID | None, list[uuid.UUID]] = defaultdict(list)
    for a in accounts.values():
        children[a.parent_id].append(a.id)
    out, stack = set(), [root]
    while stack:
        cur = stack.pop()
        out.add(cur)
        stack.extend(children.get(cur, []))
    return out


def ledger(s: Session, actor: Actor, q: LedgerQuery) -> LedgerOut:
    fy = get_year(s, q.fiscal_year_id)
    start, end = _range(fy.start_date, fy.end_date, q.date_from, q.date_to)
    accounts = {a.id: a for a in s.scalars(select(Account))}
    root = accounts.get(q.account_id)
    if root is None:
        raise NotFoundError("حساب یافت نشد")

    filters = [
        Voucher.fiscal_year_id == fy.id,
        Voucher.status == "final",
        VoucherLine.account_id.in_(_descendants(accounts, root.id)),
    ]
    if q.detail_account_id:
        filters.append(VoucherLine.detail_account_id == q.detail_account_id)
    if actor.branch_ids is not None:
        filters.append(Voucher.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    in_period = [Voucher.document_date >= start, Voucher.document_date <= end]

    def amounts(*extra: ColumnElement[bool]) -> Select:  # type: ignore[type-arg]
        return (
            select(VoucherLine.debit, VoucherLine.credit)
            .join(Voucher, Voucher.id == VoucherLine.voucher_id)
            .where(*filters, *extra)
        )

    opening = _net(s, amounts(Voucher.document_date < start))
    p_debit, p_credit = _sides(s, amounts(*in_period))
    total = s.scalar(select(func.count()).select_from(amounts(*in_period).subquery())) or 0

    order = (Voucher.document_date, Voucher.number, VoucherLine.line_no)
    offset = (q.page - 1) * q.page_size
    # Balance carried into this page = opening + every row on earlier pages.
    carried = opening + (
        _net(s, amounts(*in_period).order_by(*order).limit(offset)) if offset else ZERO
    )
    rows_db = s.execute(
        select(VoucherLine, Voucher)
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(*filters, *in_period)
        .order_by(*order)
        .offset(offset)
        .limit(q.page_size)
    ).all()
    det_ids = {ln.detail_account_id for ln, _ in rows_db if ln.detail_account_id}
    details = (
        {
            d.id: d.name
            for d in s.scalars(select(DetailAccount).where(DetailAccount.id.in_(det_ids)))
        }
        if det_ids
        else {}
    )
    rows, running = [], carried
    for ln, v in rows_db:
        running += ln.debit - ln.credit
        rows.append(
            LedgerRow(
                voucher_id=v.id,
                voucher_number=v.number or 0,
                document_date=v.document_date,
                account_code=accounts[ln.account_id].code,
                detail_account_name=details.get(ln.detail_account_id)
                if ln.detail_account_id
                else None,
                description=ln.description or v.description,
                debit=ln.debit,
                credit=ln.credit,
                balance=running,
            )
        )
    return LedgerOut(
        account_code=root.code,
        account_name=root.name,
        opening_balance=opening,
        rows=rows,
        total=total,
        page=q.page,
        page_size=q.page_size,
        period_debit=p_debit,
        period_credit=p_credit,
        closing_balance=opening + p_debit - p_credit,
    )


def _net(s: Session, stmt: Select) -> Decimal:  # type: ignore[type-arg]
    sub = stmt.subquery()
    return Decimal(s.scalar(select(func.coalesce(func.sum(sub.c.debit - sub.c.credit), 0))) or 0)


def _sides(s: Session, stmt: Select) -> tuple[Decimal, Decimal]:  # type: ignore[type-arg]
    sub = stmt.subquery()
    d, c = s.execute(
        select(func.coalesce(func.sum(sub.c.debit), 0), func.coalesce(func.sum(sub.c.credit), 0))
    ).one()
    return Decimal(d), Decimal(c)


def journal(
    s: Session,
    actor: Actor,
    fy_id: uuid.UUID,
    d_from: date | None,
    d_to: date | None,
    page: int,
    page_size: int,
) -> Page[VoucherOut]:
    fy = get_year(s, fy_id)
    start, end = _range(fy.start_date, fy.end_date, d_from, d_to)
    stmt = _scope(
        select(Voucher).where(
            Voucher.fiscal_year_id == fy.id,
            Voucher.status == "final",
            Voucher.document_date >= start,
            Voucher.document_date <= end,
        ),
        actor,
    )
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    vs = s.scalars(
        stmt.order_by(Voucher.document_date, Voucher.number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return Page[VoucherOut](
        items=[voucher_out(s, v) for v in vs], total=total, page=page, page_size=page_size
    )
