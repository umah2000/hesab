"""Chart of accounts, detail accounts and default seeding."""

from __future__ import annotations

import uuid

from sqlalchemy import exists, select, true
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.accounting.defaults import CHART, EVENTS
from app.modules.accounting.models import Account, DetailAccount, PostingRule, VoucherLine
from app.modules.accounting.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountUpdateIn,
    DetailAccountCreateIn,
    DetailAccountOut,
    DetailAccountUpdateIn,
)
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor

_CHILD_LEVEL = {None: "group", "group": "general", "general": "subsidiary"}


def check_version(row_version: bytes, expected: str, what: str = "این رکورد") -> None:
    if version_to_str(row_version) != expected.lower():
        raise ConflictError(
            f"{what} هم‌زمان تغییر کرده است؛ صفحه را تازه کنید", code="version_conflict"
        )


def account_out(a: Account) -> AccountOut:
    return AccountOut(
        id=a.id,
        code=a.code,
        name=a.name,
        level=a.level,  # type: ignore[arg-type]
        parent_id=a.parent_id,
        category=a.category,  # type: ignore[arg-type]
        nature=a.nature,  # type: ignore[arg-type]
        requires_detail=a.requires_detail,
        is_active=a.is_active,
        is_system=a.is_system,
        row_version=version_to_str(a.row_version),
    )


def seed_defaults(s: Session) -> bool:
    """Create the default chart and posting rules if the chart is empty. Returns True if seeded."""
    seeded = False
    if s.scalar(select(Account.id).limit(1)) is None:
        for g, generals in CHART:
            group = Account(
                code=g.code,
                name=g.name,
                level="group",
                category=g.category,
                nature=g.nature,
                is_system=True,
            )
            s.add(group)
            s.flush()
            for gen, subs in generals:
                general = Account(
                    code=gen.code,
                    name=gen.name,
                    level="general",
                    parent_id=group.id,
                    category=g.category,
                    nature=gen.nature or g.nature,
                    is_system=True,
                )
                s.add(general)
                s.flush()
                for sub in subs:
                    s.add(
                        Account(
                            code=sub.code,
                            name=sub.name,
                            level="subsidiary",
                            parent_id=general.id,
                            category=g.category,
                            nature=sub.nature or general.nature,
                            requires_detail=sub.requires_detail,
                            is_system=True,
                        )
                    )
        s.flush()
        seeded = True
    by_code = {a.code: a for a in s.scalars(select(Account))}
    existing = {(r.event_type, r.line_role) for r in s.scalars(select(PostingRule))}
    for ev in EVENTS:
        for role in ev.roles:
            acc = by_code.get(role.default_code)
            if (ev.event_type, role.role) not in existing and acc is not None:
                s.add(PostingRule(event_type=ev.event_type, line_role=role.role, account_id=acc.id))
    s.flush()
    return seeded


def list_accounts(s: Session) -> list[AccountOut]:
    return [account_out(a) for a in s.scalars(select(Account).order_by(Account.code))]


def get_account(s: Session, account_id: uuid.UUID) -> Account:
    a = s.get(Account, account_id)
    if a is None:
        raise NotFoundError("حساب یافت نشد")
    return a


def create_account(s: Session, actor: Actor, data: AccountCreateIn) -> AccountOut:
    if s.scalar(select(Account.id).where(Account.code == data.code)):
        raise ConflictError("کد حساب تکراری است", code="account_code_taken")
    parent = get_account(s, data.parent_id) if data.parent_id else None
    if parent is not None:
        if parent.level == "subsidiary":
            raise DomainError(
                "زیر حساب معین نمی‌توان حساب تعریف کرد؛ از تفصیلی استفاده کنید",
                code="invalid_parent",
            )
        if not data.code.startswith(parent.code) or len(data.code) <= len(parent.code):
            raise DomainError(
                f"کد حساب باید با کد حساب بالادست ({parent.code}) شروع شود", code="invalid_code"
            )
        category, nature = parent.category, data.nature or parent.nature
    else:
        if data.category is None or data.nature is None:
            raise DomainError("برای گروه حساب، نوع و ماهیت الزامی است", code="category_required")
        category, nature = data.category, data.nature
    acc = Account(
        code=data.code,
        name=data.name,
        level=_CHILD_LEVEL[parent.level if parent else None],
        parent_id=parent.id if parent else None,
        category=category,
        nature=nature,
        requires_detail=data.requires_detail,
        is_active=True,
        is_system=False,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(acc)
    s.flush()
    audit.record(
        s,
        "accounting.account_created",
        user_id=actor.user_id,
        entity_type="account",
        entity_id=acc.id,
        data={"code": acc.code, "name": acc.name},
    )
    return account_out(acc)


def update_account(
    s: Session, actor: Actor, account_id: uuid.UUID, data: AccountUpdateIn, version: str
) -> AccountOut:
    acc = get_account(s, account_id)
    check_version(acc.row_version, version, "این حساب")
    changes = data.model_dump(exclude_none=True)
    if changes.get("is_active") is False:
        if s.scalar(select(exists().where(PostingRule.account_id == acc.id))):
            raise DomainError(
                "این حساب در قواعد ثبت خودکار استفاده شده است؛ ابتدا قاعده را تغییر دهید",
                code="account_in_use",
            )
        if s.scalar(
            select(exists().where(Account.parent_id == acc.id, Account.is_active == true()))
        ):
            raise DomainError("ابتدا زیرحساب‌های فعال را غیرفعال کنید", code="has_active_children")
    for k, v in changes.items():
        setattr(acc, k, v)
    acc.updated_by = actor.user_id
    acc.updated_at = utcnow()
    s.flush()
    s.refresh(acc)
    audit.record(
        s,
        "accounting.account_updated",
        user_id=actor.user_id,
        entity_type="account",
        entity_id=acc.id,
        data=changes,
    )
    return account_out(acc)


def account_has_postings(s: Session, account_id: uuid.UUID) -> bool:
    return bool(s.scalar(select(exists().where(VoucherLine.account_id == account_id))))


# --- detail accounts --------------------------------------------------------


def detail_out(d: DetailAccount) -> DetailAccountOut:
    return DetailAccountOut(
        id=d.id,
        code=d.code,
        name=d.name,
        kind=d.kind,  # type: ignore[arg-type]
        is_active=d.is_active,
        row_version=version_to_str(d.row_version),
    )


def list_details(s: Session, q: str | None = None) -> list[DetailAccountOut]:
    stmt = select(DetailAccount).order_by(DetailAccount.code)
    if q:
        stmt = stmt.where(DetailAccount.name.ilike(f"%{q}%") | DetailAccount.code.ilike(f"%{q}%"))
    return [detail_out(d) for d in s.scalars(stmt.limit(500))]


def create_detail(s: Session, actor: Actor, data: DetailAccountCreateIn) -> DetailAccountOut:
    if s.scalar(select(DetailAccount.id).where(DetailAccount.code == data.code)):
        raise ConflictError("کد تفصیلی تکراری است", code="detail_code_taken")
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
    audit.record(
        s,
        "accounting.detail_created",
        user_id=actor.user_id,
        entity_type="detail_account",
        entity_id=d.id,
        data={"code": d.code},
    )
    return detail_out(d)


def update_detail(
    s: Session, actor: Actor, detail_id: uuid.UUID, data: DetailAccountUpdateIn, version: str
) -> DetailAccountOut:
    d = s.get(DetailAccount, detail_id)
    if d is None:
        raise NotFoundError("حساب تفصیلی یافت نشد")
    check_version(d.row_version, version, "این حساب تفصیلی")
    changes = data.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(d, k, v)
    d.updated_by = actor.user_id
    d.updated_at = utcnow()
    s.flush()
    s.refresh(d)
    audit.record(
        s,
        "accounting.detail_updated",
        user_id=actor.user_id,
        entity_type="detail_account",
        entity_id=d.id,
        data=changes,
    )
    return detail_out(d)
