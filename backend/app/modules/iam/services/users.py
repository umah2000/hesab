"""User administration."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.http import Page, PageQuery
from app.core.security import hash_password
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser, Role, UserScope
from app.modules.iam.permissions import ADMIN_ROLE
from app.modules.iam.schemas import RoleRef, UserCreateIn, UserOut, UserUpdateIn
from app.modules.iam.services.auth import (
    active_admin_count,
    forget_sessions_after_commit,
    revoke_user_sessions,
    validate_password,
)
from app.modules.organization.models import Branch


def to_out(u: AppUser) -> UserOut:
    locked_until = u.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=utcnow().tzinfo)
    return UserOut(
        id=u.id,
        username=u.username,
        full_name=u.full_name,
        is_active=u.is_active,
        must_change_password=u.must_change_password,
        is_locked=locked_until is not None and locked_until > utcnow(),
        last_login_at=u.last_login_at,
        roles=[RoleRef(id=r.id, code=r.code, name=r.name) for r in u.roles],
        all_branches=any(sc.branch_id is None for sc in u.scopes),
        branch_ids=[sc.branch_id for sc in u.scopes if sc.branch_id is not None],
        row_version=version_to_str(u.row_version),
        created_at=u.created_at,
    )


def _get(s: Session, user_id: uuid.UUID) -> AppUser:
    user = s.get(AppUser, user_id)
    if user is None:
        raise NotFoundError("کاربر یافت نشد")
    return user


def _check_version(user: AppUser, expected: str) -> None:
    if version_to_str(user.row_version) != expected.lower():
        raise ConflictError(
            "این کاربر هم‌زمان توسط شخص دیگری تغییر کرده است؛ صفحه را تازه کنید",
            code="version_conflict",
        )


def _roles(s: Session, role_ids: list[uuid.UUID]) -> list[Role]:
    ids = set(role_ids)
    roles = list(s.scalars(select(Role).where(Role.id.in_(ids))))
    if len(roles) != len(ids):
        raise DomainError("نقش نامعتبر است", code="invalid_role")
    return roles


def _scope_ids(
    s: Session, actor: Actor, all_branches: bool, branch_ids: list[uuid.UUID]
) -> set[uuid.UUID | None]:
    if all_branches:
        if actor.branch_ids is not None:
            raise DomainError(
                "فقط کاربر با دسترسی همه شعب می‌تواند این دسترسی را بدهد", code="scope_escalation"
            )
        return {None}
    ids = set(branch_ids)
    if not ids:
        raise DomainError("حداقل یک شعبه یا «همه شعب» را انتخاب کنید", code="scope_required")
    found = set(s.scalars(select(Branch.id).where(Branch.id.in_(ids))))
    if found != ids:
        raise DomainError("شعبه نامعتبر است", code="invalid_branch")
    if not all(actor.can_access_branch(b) for b in ids):
        raise DomainError(
            "نمی‌توانید به شعبه‌ای خارج از دسترسی خود مجوز بدهید", code="scope_escalation"
        )
    return set(ids)


def _apply_scopes(user: AppUser, wanted: set[uuid.UUID | None]) -> None:
    """Diff instead of replace, so the (user_id, branch_id) unique key never collides."""
    for sc in list(user.scopes):
        if sc.branch_id not in wanted:
            user.scopes.remove(sc)
    have = {sc.branch_id for sc in user.scopes}
    for b in wanted - have:
        user.scopes.append(UserScope(branch_id=b))


def list_users(s: Session, q: PageQuery) -> Page[UserOut]:
    stmt = select(AppUser)
    if q.q:
        like = f"%{q.q}%"
        stmt = stmt.where(or_(AppUser.username.ilike(like), AppUser.full_name.ilike(like)))
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = s.scalars(stmt.order_by(AppUser.username).offset(q.offset).limit(q.page_size))
    return Page[UserOut](
        items=[to_out(u) for u in rows], total=total, page=q.page, page_size=q.page_size
    )


def get_user(s: Session, user_id: uuid.UUID) -> UserOut:
    return to_out(_get(s, user_id))


def create_user(s: Session, actor: Actor, data: UserCreateIn) -> UserOut:
    if s.scalar(select(AppUser.id).where(AppUser.username == data.username)):
        raise ConflictError("این نام کاربری قبلاً ثبت شده است", code="username_taken")
    validate_password(data.password, data.username)
    user = AppUser(
        username=data.username,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        must_change_password=data.must_change_password,
        is_active=True,
        failed_attempts=0,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    user.roles = _roles(s, data.role_ids)
    s.add(user)
    _apply_scopes(user, _scope_ids(s, actor, data.all_branches, data.branch_ids))
    s.flush()
    out = to_out(user)
    audit.record(
        s,
        "users.created",
        user_id=actor.user_id,
        entity_type="app_user",
        entity_id=user.id,
        data={
            "username": user.username,
            "roles": [r.code for r in user.roles],
            "all_branches": out.all_branches,
            "branch_ids": [str(b) for b in out.branch_ids],
        },
    )
    return out


def update_user(
    s: Session, actor: Actor, user_id: uuid.UUID, data: UserUpdateIn, version: str
) -> UserOut:
    forget_sessions_after_commit(s)  # permissions or status may change
    user = _get(s, user_id)
    _check_version(user, version)
    before = to_out(user).model_dump(mode="json", exclude={"row_version"})
    was_admin = any(r.code == ADMIN_ROLE for r in user.roles)

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.role_ids is not None:
        user.roles = _roles(s, data.role_ids)
    if data.all_branches is not None or data.branch_ids is not None:
        _apply_scopes(user, _scope_ids(s, actor, bool(data.all_branches), data.branch_ids or []))
    if data.is_active is not None:
        if not data.is_active and user.id == actor.user_id:
            raise DomainError("نمی‌توانید حساب خودتان را غیرفعال کنید", code="self_deactivate")
        user.is_active = data.is_active
        if not data.is_active:
            revoke_user_sessions(s, user.id)

    is_admin_now = user.is_active and any(r.code == ADMIN_ROLE for r in user.roles)
    if was_admin and not is_admin_now and active_admin_count(s, excluding=user.id) == 0:
        raise DomainError("حداقل یک مدیر سیستم فعال باید باقی بماند", code="last_admin")

    # Always touch the row so its ROWVERSION moves even when only links changed.
    user.updated_by = actor.user_id
    user.updated_at = utcnow()
    s.flush()
    s.refresh(user)
    out = to_out(user)
    audit.record(
        s,
        "users.updated",
        user_id=actor.user_id,
        entity_type="app_user",
        entity_id=user.id,
        data={"before": before, "after": out.model_dump(mode="json", exclude={"row_version"})},
    )
    return out


def reset_password(s: Session, actor: Actor, user_id: uuid.UUID, new_password: str) -> None:
    user = _get(s, user_id)
    validate_password(new_password, user.username)
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    user.failed_attempts = 0
    user.locked_until = None
    user.updated_by = actor.user_id
    revoke_user_sessions(s, user.id)
    audit.record(
        s, "users.password_reset", user_id=actor.user_id, entity_type="app_user", entity_id=user.id
    )


def unlock(s: Session, actor: Actor, user_id: uuid.UUID) -> UserOut:
    user = _get(s, user_id)
    user.locked_until = None
    user.failed_attempts = 0
    user.updated_by = actor.user_id
    s.flush()
    s.refresh(user)
    audit.record(
        s, "users.unlocked", user_id=actor.user_id, entity_type="app_user", entity_id=user.id
    )
    return to_out(user)
