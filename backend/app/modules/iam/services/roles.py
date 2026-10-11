"""Roles, the permission catalog and initial setup."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.iam.models import Permission, Role, user_role
from app.modules.iam.permissions import ADMIN_ROLE, CATALOG, CODES, SYSTEM_ROLES
from app.modules.iam.schemas import PermissionOut, RoleCreateIn, RoleOut, RoleUpdateIn


def sync_catalog(s: Session) -> None:
    """Upsert permissions from code; create missing system roles. Never touches custom edits."""
    existing = {p.code: p for p in s.scalars(select(Permission))}
    for d in CATALOG:
        p = existing.get(d.code)
        if p is None:
            s.add(Permission(code=d.code, group_name=d.group, label=d.label))
        else:
            p.group_name, p.label = d.group, d.label
    s.flush()
    perms = {p.code: p for p in s.scalars(select(Permission))}
    roles = {r.code: r for r in s.scalars(select(Role))}
    for rd in SYSTEM_ROLES:
        role = roles.get(rd.code)
        if role is None:
            s.add(
                Role(
                    code=rd.code,
                    name=rd.name,
                    is_system=True,
                    permissions=[perms[c] for c in sorted(rd.permissions)],
                )
            )
        elif rd.code == ADMIN_ROLE:
            # The administrator role is locked to its definition so nobody can lock themselves out.
            role.permissions = [perms[c] for c in sorted(rd.permissions)]
    s.flush()


def list_permissions() -> list[PermissionOut]:
    return [PermissionOut(code=p.code, group=p.group, label=p.label) for p in CATALOG]


def _to_out(r: Role, user_count: int) -> RoleOut:
    return RoleOut(
        id=r.id,
        code=r.code,
        name=r.name,
        description=r.description,
        is_system=r.is_system,
        is_locked=r.code == ADMIN_ROLE,
        permissions=sorted(p.code for p in r.permissions),
        user_count=user_count,
        row_version=version_to_str(r.row_version),
    )


def _user_counts(s: Session) -> dict[uuid.UUID, int]:
    rows = s.execute(select(user_role.c.role_id, func.count()).group_by(user_role.c.role_id)).all()
    return {rid: int(n) for rid, n in rows}


def list_roles(s: Session) -> list[RoleOut]:
    counts = _user_counts(s)
    roles = s.scalars(select(Role).order_by(Role.is_system.desc(), Role.code))
    return [_to_out(r, counts.get(r.id, 0)) for r in roles]


def _permissions(s: Session, codes: list[str]) -> list[Permission]:
    unknown = set(codes) - CODES
    if unknown:
        raise DomainError(f"مجوز نامعتبر: {', '.join(sorted(unknown))}", code="invalid_permission")
    return (
        list(s.scalars(select(Permission).where(Permission.code.in_(set(codes))))) if codes else []
    )


def create_role(s: Session, actor: Actor, data: RoleCreateIn) -> RoleOut:
    if s.scalar(select(Role.id).where(Role.code == data.code)):
        raise ConflictError("کد نقش تکراری است", code="role_code_taken")
    role = Role(
        code=data.code,
        name=data.name,
        description=data.description,
        is_system=False,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    role.permissions = _permissions(s, data.permissions)
    s.add(role)
    s.flush()
    audit.record(
        s,
        "roles.created",
        user_id=actor.user_id,
        entity_type="role",
        entity_id=role.id,
        data={"code": role.code, "permissions": sorted(data.permissions)},
    )
    return _to_out(role, 0)


def update_role(
    s: Session, actor: Actor, role_id: uuid.UUID, data: RoleUpdateIn, version: str
) -> RoleOut:
    role = s.get(Role, role_id)
    if role is None:
        raise NotFoundError("نقش یافت نشد")
    if version_to_str(role.row_version) != version.lower():
        raise ConflictError(
            "این نقش هم‌زمان تغییر کرده است؛ صفحه را تازه کنید", code="version_conflict"
        )
    before = sorted(p.code for p in role.permissions)
    if data.permissions is not None:
        if role.code == ADMIN_ROLE:
            raise DomainError("مجوزهای نقش مدیر سیستم قابل تغییر نیست", code="role_locked")
        role.permissions = _permissions(s, data.permissions)
    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description or None
    role.updated_by = actor.user_id
    role.updated_at = utcnow()
    s.flush()
    s.refresh(role)
    after = sorted(p.code for p in role.permissions)
    audit.record(
        s,
        "roles.updated",
        user_id=actor.user_id,
        entity_type="role",
        entity_id=role.id,
        data={"permissions_before": before, "permissions_after": after, "name": role.name},
    )
    return _to_out(role, _user_counts(s).get(role.id, 0))
