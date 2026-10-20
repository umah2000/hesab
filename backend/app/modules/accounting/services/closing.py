"""Year-end closing (posting-rules.md, ADR-0011).

1. بستن حساب‌های موقت: revenue/expense balances → retained earnings (closing voucher).
2. اختتامیه: every remaining balance-sheet balance reversed to zero (closing voucher).
3. افتتاحیه: the same balances re-opened on day one of the next year (opening voucher).
The year is then closed and every period locked.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import DomainError
from app.core.money import ZERO
from app.modules.accounting.models import Account, FiscalYear, PostingRule, Voucher, VoucherLine
from app.modules.accounting.services.fiscal import ensure_year, get_year, year_out
from app.modules.accounting.services.vouchers import LineSpec, build_draft, finalize_voucher
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor

Key = tuple[uuid.UUID, uuid.UUID | None]


def _balances(s: Session, fy_id: uuid.UUID) -> dict[Key, Decimal]:
    rows = s.execute(
        select(
            VoucherLine.account_id,
            VoucherLine.detail_account_id,
            func.sum(VoucherLine.debit - VoucherLine.credit),
        )
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(Voucher.fiscal_year_id == fy_id, Voucher.status == "final")
        .group_by(VoucherLine.account_id, VoucherLine.detail_account_id)
    ).all()
    return {(a, d): Decimal(b) for a, d, b in rows if b}


def _reversing_lines(balances: dict[Key, Decimal], description: str) -> list[LineSpec]:
    """Lines that bring every balance to zero (debit balance → credit line and vice versa)."""
    lines = []
    for (acc, det), bal in sorted(balances.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        if bal > 0:
            lines.append(LineSpec(acc, ZERO, bal, det, description))
        elif bal < 0:
            lines.append(LineSpec(acc, -bal, ZERO, det, description))
    return lines


def close_year(s: Session, actor: Actor, fy_id: uuid.UUID) -> dict[str, object]:
    if actor.branch_ids is not None:
        raise DomainError(
            "بستن سال مالی فقط برای کاربر با دسترسی همه شعب مجاز است", code="scope_escalation"
        )
    fy: FiscalYear = get_year(s, fy_id)
    if fy.status != "open":
        raise DomainError("این سال مالی قبلاً بسته شده است", code="fiscal_year_closed")
    earlier_open = s.scalar(
        select(FiscalYear.id).where(
            FiscalYear.end_date < fy.start_date, FiscalYear.status == "open"
        )
    )
    if earlier_open:
        raise DomainError("ابتدا سال‌های مالی قبلی را ببندید", code="earlier_year_open")
    drafts = (
        s.scalar(
            select(func.count()).where(Voucher.fiscal_year_id == fy.id, Voucher.status == "draft")
        )
        or 0
    )
    if drafts:
        raise DomainError(
            f"{drafts} سند پیش‌نویس در این سال وجود دارد؛ ابتدا آن‌ها را قطعی یا حذف کنید",
            code="drafts_exist",
        )
    retained_id = s.scalar(
        select(PostingRule.account_id).where(
            PostingRule.event_type == "fiscal.year.closed",
            PostingRule.line_role == "retained_earnings",
        )
    )
    if retained_id is None:
        raise DomainError(
            "قاعده ثبت «سود (زیان) انباشته» برای بستن سال تعریف نشده است",
            code="posting_rule_missing",
        )

    categories = {a.id: a.category for a in s.scalars(select(Account))}
    balances = _balances(s, fy.id)
    temporary = {k: v for k, v in balances.items() if categories[k[0]] in ("revenue", "expense")}
    result: dict[str, object] = {"profit": "0"}

    if any(temporary.values()):
        lines = _reversing_lines(temporary, "بستن حساب‌های موقت")
        net = sum((ln.debit - ln.credit for ln in lines), ZERO)  # > 0 means profit
        result["profit"] = str(net)
        if net > 0:
            lines.append(LineSpec(retained_id, ZERO, net, None, "سود سال"))
        elif net < 0:
            lines.append(LineSpec(retained_id, -net, ZERO, None, "زیان سال"))
        v = build_draft(
            s,
            actor_id=actor.user_id,
            branch_id=None,
            document_date=fy.end_date,
            description=f"بستن حساب‌های موقت {fy.title}",
            lines=lines,
            source_type="closing",
            fiscal_year_id=fy.id,
        )
        finalize_voucher(s, v, actor.user_id, skip_period_check=True)
        result["temporary_closing_number"] = v.number

    permanent = {
        k: v
        for k, v in _balances(s, fy.id).items()
        if categories[k[0]] in ("asset", "liability", "equity")
    }
    next_fy = ensure_year(s, fy.jalali_year + 1, actor.user_id)
    if next_fy.status != "open":
        raise DomainError("سال مالی بعد بسته است", code="fiscal_year_closed")
    if any(permanent.values()):
        closing = build_draft(
            s,
            actor_id=actor.user_id,
            branch_id=None,
            document_date=fy.end_date,
            description=f"سند اختتامیه {fy.title}",
            lines=_reversing_lines(permanent, "اختتامیه"),
            source_type="closing",
            fiscal_year_id=fy.id,
        )
        finalize_voucher(s, closing, actor.user_id, skip_period_check=True)
        result["closing_number"] = closing.number
        opening_lines = [
            LineSpec(ln.account_id, ln.credit, ln.debit, ln.detail_account_id, "افتتاحیه")
            for ln in closing.lines
        ]
        opening = build_draft(
            s,
            actor_id=actor.user_id,
            branch_id=None,
            document_date=next_fy.start_date,
            description=f"سند افتتاحیه {next_fy.title}",
            lines=opening_lines,
            source_type="opening",
            fiscal_year_id=next_fy.id,
        )
        finalize_voucher(s, opening, actor.user_id, skip_period_check=True)
        result["opening_number"] = opening.number

    fy.status = "closed"
    s.info.pop("open_year_for", None)
    fy.closed_at = utcnow()
    fy.updated_by = actor.user_id
    for p in fy.periods:
        p.is_locked = True
    s.flush()
    audit.record(
        s,
        "accounting.fiscal_year_closed",
        user_id=actor.user_id,
        entity_type="fiscal_year",
        entity_id=fy.id,
        data=result,
    )
    s.refresh(fy)
    result["fiscal_year"] = year_out(fy).model_dump(mode="json")
    return result
