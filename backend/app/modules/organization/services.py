"""Organization settings, branches and cash registers."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.organization.models import Branch, CashRegister, Organization
from app.modules.organization.schemas import (
    BranchCreateIn,
    BranchOut,
    BranchUpdateIn,
    CashRegisterCreateIn,
    CashRegisterOut,
    CashRegisterUpdateIn,
    OrganizationOut,
    OrganizationUpdateIn,
)


def _check_version(row_version: bytes, expected: str) -> None:
    if version_to_str(row_version) != expected.lower():
        raise ConflictError(
            "این رکورد هم‌زمان تغییر کرده است؛ صفحه را تازه کنید", code="version_conflict"
        )


def _org(s: Session) -> Organization:
    org: Organization | None = s.scalar(select(Organization))
    if org is None:
        raise NotFoundError("سازمان هنوز راه‌اندازی نشده است (flask setup)")
    return org


def _org_out(o: Organization) -> OrganizationOut:
    return OrganizationOut(
        id=o.id,
        name=o.name,
        display_currency=o.display_currency,  # type: ignore[arg-type]
        timezone=o.timezone,
        negative_stock_policy=o.negative_stock_policy,  # type: ignore[arg-type]
        last_offsite_backup_at=o.last_offsite_backup_at,
        row_version=version_to_str(o.row_version),
    )


def get_organization(s: Session) -> OrganizationOut:
    return _org_out(_org(s))


def update_organization(
    s: Session, actor: Actor, data: OrganizationUpdateIn, version: str
) -> OrganizationOut:
    org = _org(s)
    _check_version(org.row_version, version)
    changes = data.model_dump(exclude_none=True)
    before = {k: getattr(org, k) for k in changes}
    for k, v in changes.items():
        setattr(org, k, v)
    org.updated_by = actor.user_id
    org.updated_at = utcnow()
    s.flush()
    s.refresh(org)
    audit.record(
        s,
        "settings.updated",
        user_id=actor.user_id,
        entity_type="organization",
        entity_id=org.id,
        data={"before": before, "after": changes},
    )
    return _org_out(org)


def ensure_organization(s: Session, name: str) -> Organization:
    org: Organization | None = s.scalar(select(Organization))
    if org is None:
        org = Organization(
            name=name, display_currency="IRT", timezone="Asia/Tehran", negative_stock_policy="warn"
        )
        s.add(org)
        s.flush()
    return org


# --- branches ---------------------------------------------------------------


def _branch_out(b: Branch) -> BranchOut:
    return BranchOut(
        id=b.id,
        code=b.code,
        name=b.name,
        address=b.address,
        is_active=b.is_active,
        row_version=version_to_str(b.row_version),
    )


def list_branches(s: Session, actor: Actor) -> list[BranchOut]:
    stmt = select(Branch).order_by(Branch.code)
    if actor.branch_ids is not None:
        stmt = stmt.where(Branch.id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    return [_branch_out(b) for b in s.scalars(stmt)]


def _branch_for(s: Session, actor: Actor, branch_id: uuid.UUID) -> Branch:
    b = s.get(Branch, branch_id)
    # Out-of-scope branches look exactly like missing ones.
    if b is None or not actor.can_access_branch(b.id):
        raise NotFoundError("شعبه یافت نشد")
    return b


def create_branch(s: Session, actor: Actor, data: BranchCreateIn) -> BranchOut:
    if actor.branch_ids is not None:
        raise DomainError(
            "فقط کاربر با دسترسی همه شعب می‌تواند شعبه تعریف کند", code="scope_escalation"
        )
    code = data.code.upper()
    if s.scalar(select(Branch.id).where(Branch.code == code)):
        raise ConflictError("کد شعبه تکراری است", code="branch_code_taken")
    b = Branch(
        code=code,
        name=data.name,
        address=data.address,
        is_active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(b)
    s.flush()
    audit.record(
        s,
        "branches.created",
        user_id=actor.user_id,
        entity_type="branch",
        entity_id=b.id,
        branch_id=b.id,
        data={"code": code, "name": b.name},
    )
    return _branch_out(b)


def update_branch(
    s: Session, actor: Actor, branch_id: uuid.UUID, data: BranchUpdateIn, version: str
) -> BranchOut:
    b = _branch_for(s, actor, branch_id)
    _check_version(b.row_version, version)
    changes = data.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(b, k, v)
    b.updated_by = actor.user_id
    b.updated_at = utcnow()
    s.flush()
    s.refresh(b)
    audit.record(
        s,
        "branches.updated",
        user_id=actor.user_id,
        entity_type="branch",
        entity_id=b.id,
        branch_id=b.id,
        data=changes,
    )
    return _branch_out(b)


# --- cash registers ---------------------------------------------------------


def _register_out(r: CashRegister) -> CashRegisterOut:
    return CashRegisterOut(
        id=r.id,
        branch_id=r.branch_id,
        code=r.code,
        name=r.name,
        is_active=r.is_active,
        row_version=version_to_str(r.row_version),
    )


def list_registers(s: Session, actor: Actor, branch_id: uuid.UUID) -> list[CashRegisterOut]:
    _branch_for(s, actor, branch_id)
    rows = s.scalars(
        select(CashRegister).where(CashRegister.branch_id == branch_id).order_by(CashRegister.code)
    )
    return [_register_out(r) for r in rows]


def create_register(s: Session, actor: Actor, data: CashRegisterCreateIn) -> CashRegisterOut:
    branch = _branch_for(s, actor, data.branch_id)
    code = data.code.upper()
    exists = s.scalar(
        select(CashRegister.id).where(
            CashRegister.branch_id == branch.id, CashRegister.code == code
        )
    )
    if exists:
        raise ConflictError("کد صندوق در این شعبه تکراری است", code="register_code_taken")
    r = CashRegister(
        branch_id=branch.id,
        code=code,
        name=data.name,
        is_active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(r)
    s.flush()
    audit.record(
        s,
        "registers.created",
        user_id=actor.user_id,
        entity_type="cash_register",
        entity_id=r.id,
        branch_id=branch.id,
        data={"code": code, "name": r.name},
    )
    return _register_out(r)


def update_register(
    s: Session, actor: Actor, register_id: uuid.UUID, data: CashRegisterUpdateIn, version: str
) -> CashRegisterOut:
    r = s.get(CashRegister, register_id)
    if r is None or not actor.can_access_branch(r.branch_id):
        raise NotFoundError("صندوق یافت نشد")
    _check_version(r.row_version, version)
    changes = data.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(r, k, v)
    r.updated_by = actor.user_id
    r.updated_at = utcnow()
    s.flush()
    s.refresh(r)
    audit.record(
        s,
        "registers.updated",
        user_id=actor.user_id,
        entity_type="cash_register",
        entity_id=r.id,
        branch_id=r.branch_id,
        data=changes,
    )
    return _register_out(r)
