"""Vouchers: draft → final, reversal. Rules from posting-rules.md §1 and ADR-0011.

- Drafts are editable, may be unbalanced and carry no number.
- Finalising requires balance, >=2 lines, an open year and an unlocked period;
  it allocates the next gap-free number. Final vouchers never change.
- Corrections are made by a reversing voucher, linked both ways.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import DomainError, NotFoundError
from app.core.http import Page
from app.core.money import ZERO
from app.core.numbering import next_number
from app.modules.accounting.models import Account, DetailAccount, Voucher, VoucherLine
from app.modules.accounting.schemas import (
    VoucherIn,
    VoucherLineOut,
    VoucherOut,
    VoucherQuery,
    VoucherSummaryOut,
)
from app.modules.accounting.services.chart import check_version
from app.modules.accounting.services.fiscal import open_year_for
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.organization.models import Branch

DOC_TYPE = "voucher"


@dataclass(frozen=True)
class LineSpec:
    account_id: uuid.UUID
    debit: Decimal
    credit: Decimal
    detail_account_id: uuid.UUID | None = None
    description: str | None = None


# --- serialisation ----------------------------------------------------------


def voucher_out(s: Session, v: Voucher) -> VoucherOut:
    acc_ids = {ln.account_id for ln in v.lines}
    det_ids = {ln.detail_account_id for ln in v.lines if ln.detail_account_id}
    accounts = (
        {a.id: a for a in s.scalars(select(Account).where(Account.id.in_(acc_ids)))}
        if acc_ids
        else {}
    )
    details = (
        {d.id: d for d in s.scalars(select(DetailAccount).where(DetailAccount.id.in_(det_ids)))}
        if det_ids
        else {}
    )
    lines = []
    for ln in v.lines:
        a = accounts[ln.account_id]
        d = details.get(ln.detail_account_id) if ln.detail_account_id else None
        lines.append(
            VoucherLineOut(
                id=ln.id,
                line_no=ln.line_no,
                account_id=a.id,
                account_code=a.code,
                account_name=a.name,
                detail_account_id=d.id if d else None,
                detail_account_code=d.code if d else None,
                detail_account_name=d.name if d else None,
                debit=ln.debit,
                credit=ln.credit,
                description=ln.description,
            )
        )
    return VoucherOut(
        id=v.id,
        branch_id=v.branch_id,
        fiscal_year_id=v.fiscal_year_id,
        number=v.number,
        document_date=v.document_date,
        status=v.status,  # type: ignore[arg-type]
        description=v.description,
        source_type=v.source_type,
        source_ref=v.source_ref,
        total_debit=v.total_debit,
        total_credit=v.total_credit,
        is_balanced=v.total_debit == v.total_credit and v.total_debit > 0,
        reversal_of_id=v.reversal_of_id,
        reversed_by_id=v.reversed_by_id,
        finalized_at=v.finalized_at,
        created_at=v.created_at,
        row_version=version_to_str(v.row_version),
        lines=lines,
    )


# --- validation -------------------------------------------------------------


def _validate_lines(s: Session, lines: list[LineSpec]) -> None:
    acc_ids = {ln.account_id for ln in lines}
    accounts = {a.id: a for a in s.scalars(select(Account).where(Account.id.in_(acc_ids)))}
    det_ids = {ln.detail_account_id for ln in lines if ln.detail_account_id}
    details = (
        {d.id: d for d in s.scalars(select(DetailAccount).where(DetailAccount.id.in_(det_ids)))}
        if det_ids
        else {}
    )
    for i, ln in enumerate(lines, start=1):
        a = accounts.get(ln.account_id)
        if a is None:
            raise DomainError(f"ردیف {i}: حساب یافت نشد", code="invalid_account")
        if a.level != "subsidiary":
            raise DomainError(
                f"ردیف {i}: فقط حساب معین قابل ثبت است ({a.code})", code="account_not_postable"
            )
        if not a.is_active:
            raise DomainError(f"ردیف {i}: حساب {a.code} غیرفعال است", code="account_inactive")
        if ln.detail_account_id:
            d = details.get(ln.detail_account_id)
            if d is None or not d.is_active:
                raise DomainError(
                    f"ردیف {i}: حساب تفصیلی نامعتبر یا غیرفعال است", code="invalid_detail"
                )
        elif a.requires_detail:
            raise DomainError(
                f"ردیف {i}: حساب {a.code} ({a.name}) نیازمند حساب تفصیلی است",
                code="detail_required",
            )
        if ln.debit < 0 or ln.credit < 0:
            raise DomainError(f"ردیف {i}: مبلغ منفی مجاز نیست", code="negative_amount")
        if (ln.debit > 0) == (ln.credit > 0):
            raise DomainError(
                f"ردیف {i}: هر ردیف باید فقط بدهکار یا فقط بستانکار باشد", code="one_side_required"
            )


def _check_branch(s: Session, actor: Actor | None, branch_id: uuid.UUID | None) -> None:
    if branch_id is None:
        return
    b = s.get(Branch, branch_id)
    if b is None or (actor is not None and not actor.can_access_branch(branch_id)):
        raise NotFoundError("شعبه یافت نشد")


def _apply_lines(s: Session, v: Voucher, lines: list[LineSpec]) -> None:
    if v.lines:
        # Delete old lines first: (voucher_id, line_no) is unique and the ORM
        # would otherwise insert the new lines before deleting the old ones.
        v.lines.clear()
        s.flush()
    for i, ln in enumerate(lines, start=1):
        v.lines.append(
            VoucherLine(
                line_no=i,
                account_id=ln.account_id,
                detail_account_id=ln.detail_account_id,
                debit=ln.debit,
                credit=ln.credit,
                description=ln.description,
            )
        )
    v.total_debit = sum((ln.debit for ln in lines), ZERO)
    v.total_credit = sum((ln.credit for ln in lines), ZERO)


def _specs(data: VoucherIn) -> list[LineSpec]:
    return [
        LineSpec(
            account_id=ln.account_id,
            detail_account_id=ln.detail_account_id,
            debit=ln.debit,
            credit=ln.credit,
            description=ln.description or None,
        )
        for ln in data.lines
    ]


# --- operations -------------------------------------------------------------


def get_voucher(s: Session, actor: Actor | None, voucher_id: uuid.UUID) -> Voucher:
    v = s.get(Voucher, voucher_id)
    # Company-level vouchers (branch NULL) are visible to all-branch users only.
    if v is None or (
        actor is not None
        and actor.branch_ids is not None
        and (v.branch_id is None or v.branch_id not in actor.branch_ids)
    ):
        raise NotFoundError("سند یافت نشد")
    return v


def build_draft(
    s: Session,
    *,
    actor_id: uuid.UUID | None,
    branch_id: uuid.UUID | None,
    document_date: date,
    description: str | None,
    lines: list[LineSpec],
    source_type: str = "manual",
    source_ref: str | None = None,
    source_id: uuid.UUID | None = None,
    fiscal_year_id: uuid.UUID | None = None,
) -> Voucher:
    _validate_lines(s, lines)
    fy_id = fiscal_year_id or open_year_for(s, document_date).id
    v = Voucher(
        branch_id=branch_id,
        fiscal_year_id=fy_id,
        document_date=document_date,
        description=description,
        status="draft",
        source_type=source_type,
        source_ref=source_ref,
        source_id=source_id,
        created_by=actor_id,
        updated_by=actor_id,
    )
    s.add(v)
    _apply_lines(s, v, lines)
    s.flush()
    return v


def finalize_voucher(
    s: Session, v: Voucher, actor_id: uuid.UUID | None, *, skip_period_check: bool = False
) -> Voucher:
    if v.status != "draft":
        raise DomainError("فقط سند پیش‌نویس قابل قطعی شدن است", code="not_draft")
    if len(v.lines) < 2:
        raise DomainError("سند باید حداقل دو ردیف داشته باشد", code="too_few_lines")
    if v.total_debit != v.total_credit or v.total_debit <= 0:
        diff = v.total_debit - v.total_credit
        raise DomainError(f"سند تراز نیست (اختلاف: {diff:,.0f} ریال)", code="unbalanced")
    if not skip_period_check:
        fy = open_year_for(s, v.document_date)
        if fy.id != v.fiscal_year_id:
            raise DomainError("تاریخ سند خارج از سال مالی آن است", code="date_outside_year")
    _validate_lines(
        s, [LineSpec(ln.account_id, ln.debit, ln.credit, ln.detail_account_id) for ln in v.lines]
    )
    v.number = next_number(s, DOC_TYPE, v.fiscal_year_id)
    v.status = "final"
    v.finalized_at = utcnow()
    v.finalized_by = actor_id
    v.updated_by = actor_id
    v.updated_at = utcnow()
    s.flush()
    return v


def create_draft(s: Session, actor: Actor, data: VoucherIn) -> VoucherOut:
    _check_branch(s, actor, data.branch_id)
    v = build_draft(
        s,
        actor_id=actor.user_id,
        branch_id=data.branch_id,
        document_date=data.document_date,
        description=data.description,
        lines=_specs(data),
    )
    audit.record(
        s,
        "accounting.voucher_created",
        user_id=actor.user_id,
        entity_type="voucher",
        entity_id=v.id,
        branch_id=v.branch_id,
        data={"total": str(v.total_debit), "lines": len(v.lines)},
    )
    return voucher_out(s, v)


def update_draft(
    s: Session, actor: Actor, voucher_id: uuid.UUID, data: VoucherIn, version: str
) -> VoucherOut:
    v = get_voucher(s, actor, voucher_id)
    check_version(v.row_version, version, "این سند")
    if v.status != "draft":
        raise DomainError(
            "سند قطعی قابل ویرایش نیست؛ برای اصلاح، سند برگشت صادر کنید", code="voucher_final"
        )
    if v.source_type != "manual":
        raise DomainError("سند خودکار فقط از سند مبدأ قابل تغییر است", code="voucher_auto")
    _check_branch(s, actor, data.branch_id)
    lines = _specs(data)
    _validate_lines(s, lines)
    v.fiscal_year_id = open_year_for(s, data.document_date).id
    v.branch_id = data.branch_id
    v.document_date = data.document_date
    v.description = data.description
    _apply_lines(s, v, lines)
    v.updated_by = actor.user_id
    v.updated_at = utcnow()
    s.flush()
    s.refresh(v)
    audit.record(
        s,
        "accounting.voucher_updated",
        user_id=actor.user_id,
        entity_type="voucher",
        entity_id=v.id,
        branch_id=v.branch_id,
        data={"total": str(v.total_debit)},
    )
    return voucher_out(s, v)


def delete_draft(s: Session, actor: Actor, voucher_id: uuid.UUID, version: str) -> None:
    v = get_voucher(s, actor, voucher_id)
    check_version(v.row_version, version, "این سند")
    if v.status != "draft":
        raise DomainError(
            "سند قطعی حذف نمی‌شود؛ برای اصلاح، سند برگشت صادر کنید", code="voucher_final"
        )
    audit.record(
        s,
        "accounting.voucher_draft_deleted",
        user_id=actor.user_id,
        entity_type="voucher",
        entity_id=v.id,
        branch_id=v.branch_id,
        data={"total": str(v.total_debit), "date": str(v.document_date)},
    )
    s.delete(v)
    s.flush()


def finalize(s: Session, actor: Actor, voucher_id: uuid.UUID, version: str) -> VoucherOut:
    v = get_voucher(s, actor, voucher_id)
    check_version(v.row_version, version, "این سند")
    finalize_voucher(s, v, actor.user_id)
    s.refresh(v)
    audit.record(
        s,
        "accounting.voucher_finalized",
        user_id=actor.user_id,
        entity_type="voucher",
        entity_id=v.id,
        branch_id=v.branch_id,
        data={"number": v.number, "total": str(v.total_debit)},
    )
    return voucher_out(s, v)


def reverse(
    s: Session,
    actor: Actor,
    voucher_id: uuid.UUID,
    version: str,
    document_date: date | None,
    description: str | None,
) -> VoucherOut:
    original = get_voucher(s, actor, voucher_id)
    check_version(original.row_version, version, "این سند")
    if original.status != "final":
        raise DomainError(
            "فقط سند قطعی برگشت می‌خورد؛ پیش‌نویس را ویرایش یا حذف کنید", code="not_final"
        )
    if original.reversed_by_id is not None:
        raise DomainError("این سند قبلاً برگشت خورده است", code="already_reversed")
    if original.reversal_of_id is not None:
        raise DomainError("سند برگشتی را نمی‌توان دوباره برگشت زد", code="is_reversal")
    if original.source_type in ("opening", "closing"):
        raise DomainError("سند افتتاحیه/اختتامیه برگشت‌پذیر نیست", code="not_reversible")
    rev = reverse_voucher(
        s, original, actor.user_id, document_date or original.document_date, description
    )
    return voucher_out(s, rev)


def reverse_voucher(
    s: Session,
    original: Voucher,
    actor_id: uuid.UUID | None,
    when: date,
    description: str | None,
) -> Voucher:
    """The mirror voucher of a final one, finalised; the caller has checked it may be."""
    lines = [
        LineSpec(
            account_id=ln.account_id,
            detail_account_id=ln.detail_account_id,
            debit=ln.credit,
            credit=ln.debit,
            description=ln.description,
        )
        for ln in original.lines
    ]
    rev = build_draft(
        s,
        actor_id=actor_id,
        branch_id=original.branch_id,
        document_date=when,
        description=description or f"برگشت سند شماره {original.number}",
        lines=lines,
        source_type="reversal",
        source_id=original.id,
    )
    rev.reversal_of_id = original.id
    finalize_voucher(s, rev, actor_id)
    original.reversed_by_id = rev.id
    original.updated_at = utcnow()
    s.flush()
    s.refresh(rev)
    audit.record(
        s,
        "accounting.voucher_reversed",
        user_id=actor_id,
        entity_type="voucher",
        entity_id=original.id,
        branch_id=original.branch_id,
        data={"number": original.number, "reversal_number": rev.number},
    )
    return rev


def list_vouchers(s: Session, actor: Actor, q: VoucherQuery) -> Page[VoucherSummaryOut]:
    line_count = (
        select(func.count())
        .where(VoucherLine.voucher_id == Voucher.id)
        .correlate(Voucher)
        .scalar_subquery()
    )
    stmt = select(Voucher, line_count)
    if q.fiscal_year_id:
        stmt = stmt.where(Voucher.fiscal_year_id == q.fiscal_year_id)
    if q.status:
        stmt = stmt.where(Voucher.status == q.status)
    if q.date_from:
        stmt = stmt.where(Voucher.document_date >= q.date_from)
    if q.date_to:
        stmt = stmt.where(Voucher.document_date <= q.date_to)
    if q.number:
        stmt = stmt.where(Voucher.number == q.number)
    if actor.branch_ids is not None:
        stmt = stmt.where(Voucher.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = s.execute(
        stmt.order_by(
            Voucher.document_date.desc(), Voucher.number.desc(), Voucher.created_at.desc()
        )
        .offset((q.page - 1) * q.page_size)
        .limit(q.page_size)
    ).all()
    items = [
        VoucherSummaryOut(
            id=v.id,
            number=v.number,
            document_date=v.document_date,
            status=v.status,
            description=v.description,
            source_type=v.source_type,
            total_debit=v.total_debit,
            total_credit=v.total_credit,
            reversed_by_id=v.reversed_by_id,
            reversal_of_id=v.reversal_of_id,
            line_count=int(n),
        )
        for v, n in rows
    ]
    return Page[VoucherSummaryOut](items=items, total=total, page=q.page, page_size=q.page_size)
