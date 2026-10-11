"""Login, server-side sessions, lockout and password policy (ADR-0004)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import current_app
from sqlalchemy import func, select, true, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import new_session, unit_of_work, utcnow
from app.core.errors import DomainError
from app.core.security import hash_password, hash_token, needs_rehash, new_token, verify_password
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor, NotAuthenticatedError
from app.modules.iam.models import AppUser, UserSession

_LAST_SEEN_GRANULARITY = timedelta(seconds=60)
GENERIC_LOGIN_ERROR = "نام کاربری یا رمز عبور نادرست است، یا حساب موقتاً قفل شده است"


def _settings() -> Settings:
    settings: Settings = current_app.config["SETTINGS"]
    return settings


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class LoginFailedError(DomainError):
    status_code = 401
    code = "login_failed"


def validate_password(password: str, username: str) -> None:
    if len(password) < 8:
        raise DomainError("رمز عبور باید حداقل ۸ کاراکتر باشد", code="weak_password")
    if not re.search(r"\d", password) or not re.search(r"[^\d\s]", password):
        raise DomainError("رمز عبور باید شامل حرف و عدد باشد", code="weak_password")
    if password.strip().lower() == username.strip().lower():
        raise DomainError("رمز عبور نباید با نام کاربری یکسان باشد", code="weak_password")


@dataclass(frozen=True)
class LoginResult:
    user_id: uuid.UUID
    session_token: str
    csrf_token: str
    expires_at: datetime


def check_credentials(
    s: Session, username: str, password: str, *, purpose: str = "login"
) -> AppUser | None:
    """Verify a password with lockout bookkeeping; ``None`` on any failure.

    Used by login and by supervisor approvals on a register. Failures are recorded
    in the caller's unit of work, which must be committed even though the request fails.
    """
    settings = _settings()
    now = utcnow()
    failed = "auth.login_failed" if purpose == "login" else f"auth.{purpose}_failed"
    user = s.scalar(select(AppUser).where(AppUser.username == username.strip()))
    if user is None:
        verify_password(None, password)  # equalise timing
        audit.record(s, failed, user_id=None, data={"username": username[:64]})
        return None
    if not user.is_active:
        verify_password(None, password)
        audit.record(s, failed, user_id=user.id, data={"reason": "inactive"})
        return None
    if (_aware(user.locked_until) or now) > now:
        verify_password(None, password)
        audit.record(s, failed, user_id=user.id, data={"reason": "locked"})
        return None
    if not verify_password(user.password_hash, password):
        # Login bookkeeping uses atomic SQL updates instead of the ORM, so it never
        # collides with optimistic row versions (two terminals logging in at once).
        attempts = s.execute(
            update(AppUser)
            .where(AppUser.id == user.id)
            .values(failed_attempts=AppUser.failed_attempts + 1)
            .returning(AppUser.failed_attempts)
        ).scalar_one()
        reason = "bad_password"
        if attempts >= settings.max_failed_logins:
            s.execute(
                update(AppUser)
                .where(AppUser.id == user.id)
                .values(
                    failed_attempts=0,
                    locked_until=now + timedelta(minutes=settings.lockout_minutes),
                )
            )
            reason = "locked_now"
            audit.record(
                s,
                "auth.user_locked",
                user_id=user.id,
                entity_type="app_user",
                entity_id=user.id,
            )
        audit.record(s, failed, user_id=user.id, data={"reason": reason})
        return None
    values: dict[str, object] = {"failed_attempts": 0, "locked_until": None}
    if purpose == "login":
        values["last_login_at"] = now
    if needs_rehash(user.password_hash):
        values["password_hash"] = hash_password(password)
    s.execute(update(AppUser).where(AppUser.id == user.id).values(**values))
    return user


def login(username: str, password: str, *, ip: str | None, user_agent: str | None) -> LoginResult:
    settings = _settings()
    now = utcnow()
    result: LoginResult | None = None

    # The failure bookkeeping must be committed even though the request fails,
    # so the error is raised only after the unit of work has finished.
    with unit_of_work() as s:
        user = check_credentials(s, username, password)
        if user is not None:
            token, csrf = new_token(), new_token()
            expires = now + timedelta(hours=settings.session_absolute_hours)
            sess = UserSession(
                user_id=user.id,
                token_hash=hash_token(token),
                csrf_hash=hash_token(csrf),
                last_seen_at=now,
                expires_at=expires,
                ip=ip,
                user_agent=(user_agent or "")[:300] or None,
            )
            s.add(sess)
            s.flush()
            audit.record(
                s, "auth.login", user_id=user.id, entity_type="user_session", entity_id=sess.id
            )
            result = LoginResult(user.id, token, csrf, expires)

    if result is None:
        raise LoginFailedError(GENERIC_LOGIN_ERROR)
    return result


def actor_for(user: AppUser, session_id: uuid.UUID) -> Actor:
    scopes = user.scopes
    branch_ids: frozenset[uuid.UUID] | None
    if any(sc.branch_id is None for sc in scopes):
        branch_ids = None
    else:
        branch_ids = frozenset(sc.branch_id for sc in scopes if sc.branch_id is not None)
    return Actor(
        user_id=user.id,
        username=user.username,
        session_id=session_id,
        permissions=user.permission_codes,
        branch_ids=branch_ids,
    )


def resolve_session(token: str) -> tuple[Actor, str]:
    settings = _settings()
    now = utcnow()
    s = new_session()
    try:
        sess = s.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
        if sess is None or sess.revoked_at is not None:
            raise NotAuthenticatedError("نشست نامعتبر است؛ دوباره وارد شوید")
        last_seen = _aware(sess.last_seen_at) or now
        if (_aware(sess.expires_at) or now) <= now or (
            last_seen + timedelta(minutes=settings.session_idle_minutes) <= now
        ):
            raise NotAuthenticatedError("نشست منقضی شده است؛ دوباره وارد شوید")
        user = sess.user
        if not user.is_active:
            raise NotAuthenticatedError("حساب کاربری غیرفعال است")
        if now - last_seen >= _LAST_SEEN_GRANULARITY:
            s.execute(update(UserSession).where(UserSession.id == sess.id).values(last_seen_at=now))
            s.commit()
        return actor_for(user, sess.id), sess.csrf_hash
    finally:
        s.close()


def logout(actor: Actor) -> None:
    with unit_of_work() as s:
        s.execute(
            update(UserSession)
            .where(UserSession.id == actor.session_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        audit.record(
            s,
            "auth.logout",
            user_id=actor.user_id,
            entity_type="user_session",
            entity_id=actor.session_id,
        )


def revoke_user_sessions(
    s: Session, user_id: uuid.UUID, *, except_session: uuid.UUID | None = None
) -> None:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    if except_session is not None:
        stmt = stmt.where(UserSession.id != except_session)
    s.execute(stmt)


def change_password(actor: Actor, current_password: str, new_password: str) -> None:
    with unit_of_work() as s:
        user = s.get(AppUser, actor.user_id)
        if user is None or not verify_password(user.password_hash, current_password):
            raise DomainError("رمز عبور فعلی نادرست است", code="wrong_password")
        validate_password(new_password, user.username)
        if verify_password(user.password_hash, new_password):
            raise DomainError("رمز عبور جدید باید با رمز فعلی متفاوت باشد", code="weak_password")
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        user.updated_by = actor.user_id
        revoke_user_sessions(s, user.id, except_session=actor.session_id)
        audit.record(
            s,
            "auth.password_changed",
            user_id=actor.user_id,
            entity_type="app_user",
            entity_id=user.id,
        )


def active_admin_count(s: Session, *, excluding: uuid.UUID | None = None) -> int:
    from app.modules.iam.models import Role, user_role
    from app.modules.iam.permissions import ADMIN_ROLE

    stmt = (
        select(func.count(func.distinct(AppUser.id)))
        .join(user_role, user_role.c.user_id == AppUser.id)
        .join(Role, Role.id == user_role.c.role_id)
        .where(Role.code == ADMIN_ROLE, AppUser.is_active == true())
    )
    if excluding is not None:
        stmt = stmt.where(AppUser.id != excluding)
    return int(s.scalar(stmt) or 0)
