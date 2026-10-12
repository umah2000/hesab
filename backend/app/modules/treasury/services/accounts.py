"""Cash boxes and bank accounts; each is a ``cash``/``bank`` detail account."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.accounting.models import DetailAccount, Voucher, VoucherLine
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.organization.models import Branch
from app.modules.treasury.models import MoneyAccount
from app.modules.treasury.schemas import AccountCreateIn, AccountFields, AccountOut, AccountUpdateIn

ZERO = Decimal(0)


def balances(s: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Debit − credit over final vouchers: money in the box or account."""
    if not ids:
        return {}
    rows = s.execute(
        select(VoucherLine.detail_account_id, func.sum(VoucherLine.debit - VoucherLine.credit))
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(Voucher.status == "final", VoucherLine.detail_account_id.in_(ids))
        .group_by(VoucherLine.detail_account_id)
    ).all()
    return {k: Decimal(v or 0) for k, v in rows if k is not None}


def _out(s: Session, m: MoneyAccount, d: DetailAccount, balance: Decimal) -> AccountOut:
    branch = s.get(Branch, m.branch_id) if m.branch_id else None
    return AccountOut(
        id=m.id,
        code=d.code,
        name=d.name,
        kind=m.kind,
        branch_id=m.branch_id,
        branch_name=branch.name if branch else None,
        bank_name=m.bank_name,
        bank_branch=m.bank_branch,
        account_no=m.account_no,
        iban=m.iban,
        is_active=d.is_active,
        balance=balance,
        row_version=version_to_str(m.row_version),
    )


def _apply(s: Session, m: MoneyAccount, d: DetailAccount, data: AccountFields) -> None:
    if data.branch_id is not None and s.get(Branch, data.branch_id) is None:
        raise DomainError("شعبه یافت نشد", code="bad_branch")
    if m.kind == "cash" and data.branch_id is None:
        raise DomainError("صندوق باید به یک شعبه تعلق داشته باشد", code="branch_required")
    d.name = data.name
    m.branch_id = data.branch_id
    if m.kind == "bank":
        m.bank_name, m.bank_branch = data.bank_name, data.bank_branch
        m.account_no, m.iban = data.account_no, data.iban


def create(s: Session, actor: Actor, data: AccountCreateIn) -> AccountOut:
    if s.scalar(select(DetailAccount.id).where(DetailAccount.code == data.code)):
        raise ConflictError("کد حساب (تفصیلی) تکراری است", code="account_code_taken")
    d = DetailAccount(
        code=data.code,
        name=data.name,
        kind=data.kind,
        is_active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(d)
    s.flush()
    m = MoneyAccount(id=d.id, kind=data.kind, created_by=actor.user_id, updated_by=actor.user_id)
    _apply(s, m, d, data)
    s.add(m)
    s.flush()
    audit.record(
        s,
        "treasury.account_created",
        user_id=actor.user_id,
        entity_type="money_account",
        entity_id=m.id,
        data={"code": d.code, "kind": m.kind},
    )
    s.refresh(m)
    return _out(s, m, d, ZERO)


def _get(s: Session, account_id: uuid.UUID) -> tuple[MoneyAccount, DetailAccount]:
    m = s.get(MoneyAccount, account_id)
    d = s.get(DetailAccount, account_id)
    if m is None or d is None:
        raise NotFoundError("صندوق یا حساب بانکی یافت نشد")
    return m, d


def update(
    s: Session, actor: Actor, account_id: uuid.UUID, data: AccountUpdateIn, version: str
) -> AccountOut:
    m, d = _get(s, account_id)
    check_version(m.row_version, version, "این حساب")
    bal = balances(s, [m.id]).get(m.id, ZERO)
    if not data.is_active and bal != 0:
        raise DomainError("حساب دارای مانده غیرفعال نمی‌شود", code="account_has_balance")
    _apply(s, m, d, data)
    d.is_active = data.is_active
    m.updated_by = d.updated_by = actor.user_id
    s.flush()
    s.refresh(m)
    return _out(s, m, d, bal)


def list_accounts(s: Session, actor: Actor, kind: str | None = None) -> list[AccountOut]:
    stmt = select(MoneyAccount, DetailAccount).join(
        DetailAccount, DetailAccount.id == MoneyAccount.id
    )
    if kind:
        stmt = stmt.where(MoneyAccount.kind == kind)
    rows = [
        (m, d)
        for m, d in s.execute(stmt.order_by(MoneyAccount.kind, DetailAccount.code)).all()
        if m.branch_id is None or actor.can_access_branch(m.branch_id)
    ]
    bals = balances(s, [m.id for m, _ in rows])
    return [_out(s, m, d, bals.get(m.id, ZERO)) for m, d in rows]


def require(
    s: Session,
    actor: Actor,
    account_id: uuid.UUID,
    kind: str | None = None,
    *,
    lock: bool = False,
) -> tuple[MoneyAccount, DetailAccount]:
    """An active account the actor may use; ``lock`` serialises withdrawals (key seek)."""
    m = s.get(MoneyAccount, account_id, with_for_update=lock)
    d = s.get(DetailAccount, account_id)
    if (
        m is None
        or d is None
        or (m.branch_id is not None and not actor.can_access_branch(m.branch_id))
    ):
        raise NotFoundError("صندوق یا حساب بانکی یافت نشد")
    if not d.is_active:
        raise DomainError(f"«{d.name}» غیرفعال است", code="account_inactive")
    if kind is not None and m.kind != kind:
        label = "صندوق" if kind == "cash" else "حساب بانکی"
        raise DomainError(f"«{d.name}» {label} نیست", code="wrong_account_kind")
    return m, d
