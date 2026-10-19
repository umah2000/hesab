"""Sign-in for the visitor app: short access token + rotating refresh token (ADR-0004).

* Access token: 15 minutes, sent as ``Authorization: Bearer ncm_a_…``; accepted only on
  the visitor app's endpoints, never on the back office.
* Refresh token: used once; each use returns a new pair. A refresh token presented a
  second time means a copy exists, so the whole session is revoked.
* The session itself ends after 30 days; then the visitor signs in again. Orders waiting
  on the phone are not tied to the session and survive it.
* Only users with ``distribution.visitor`` may sign in here. Tokens are stored as hashes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import new_session, unit_of_work, utcnow
from app.core.errors import PermissionDeniedError
from app.core.security import hash_token, new_token
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor, NotAuthenticatedError
from app.modules.iam.models import AppUser, MobileSession, MobileToken
from app.modules.iam.services.auth import (
    GENERIC_LOGIN_ERROR,
    LoginFailedError,
    actor_for,
    check_credentials,
)

ACCESS_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)
ACCESS_PREFIX = "ncm_a_"
REFRESH_PREFIX = "ncm_r_"
PERMISSION = "distribution.visitor"
# Where an access token is accepted (the visitor app's own endpoints).
PATHS = ("/api/v1/distribution/mobile/", "/api/v1/auth/mobile/")
_SEEN_EVERY = timedelta(seconds=60)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class TokenPair:
    user_id: uuid.UUID
    session_id: uuid.UUID
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


def _issue(s: Session, sess: MobileSession, now: datetime) -> TokenPair:
    access, refresh = ACCESS_PREFIX + new_token(), REFRESH_PREFIX + new_token()
    access_exp = min(now + ACCESS_TTL, _aware(sess.expires_at))
    s.add_all(
        [
            MobileToken(
                session_id=sess.id,
                kind="access",
                token_hash=hash_token(access),
                expires_at=access_exp,
            ),
            MobileToken(
                session_id=sess.id,
                kind="refresh",
                token_hash=hash_token(refresh),
                expires_at=sess.expires_at,
            ),
        ]
    )
    s.flush()
    return TokenPair(sess.user_id, sess.id, access, access_exp, refresh, _aware(sess.expires_at))


def login(username: str, password: str, *, device_name: str | None, ip: str | None) -> TokenPair:
    now = utcnow()
    pair: TokenPair | None = None
    denied = False
    # Failure bookkeeping (lockout, audit) is committed before the error is raised.
    with unit_of_work() as s:
        user = check_credentials(s, username, password)
        if user is not None and PERMISSION not in user.permission_codes:
            denied = True
            audit.record(s, "auth.mobile_login_denied", user_id=user.id)
        elif user is not None:
            sess = MobileSession(
                user_id=user.id,
                device_name=(device_name or "")[:100] or None,
                last_seen_at=now,
                expires_at=now + SESSION_TTL,
            )
            s.add(sess)
            s.flush()
            pair = _issue(s, sess, now)
            audit.record(
                s,
                "auth.mobile_login",
                user_id=user.id,
                entity_type="mobile_session",
                entity_id=sess.id,
                data={"device": sess.device_name, "ip": ip},
            )
    if denied:
        raise PermissionDeniedError("این حساب مجوز اپلیکیشن ویزیتور را ندارد")
    if pair is None:
        raise LoginFailedError(GENERIC_LOGIN_ERROR)
    return pair


def refresh(token: str) -> TokenPair:
    now = utcnow()
    pair: TokenPair | None = None
    reason = "نشست نامعتبر است؛ دوباره وارد شوید"
    with unit_of_work() as s:
        row = s.scalar(
            select(MobileToken)
            .where(MobileToken.token_hash == hash_token(token), MobileToken.kind == "refresh")
            .with_for_update()
        )
        sess = s.get(MobileSession, row.session_id, with_for_update=True) if row else None
        if row is not None and sess is not None and sess.revoked_at is None:
            user = s.get(AppUser, sess.user_id)
            if row.used_at is not None:
                # The same refresh token twice: someone else holds a copy.
                sess.revoked_at, sess.revoke_reason = now, "refresh_reuse"
                audit.record(
                    s,
                    "auth.mobile_refresh_reuse",
                    user_id=sess.user_id,
                    entity_type="mobile_session",
                    entity_id=sess.id,
                )
                reason = "این نشست به دلایل امنیتی بسته شد؛ دوباره وارد شوید"
            elif _aware(sess.expires_at) <= now:
                reason = "نشست منقضی شده است؛ دوباره وارد شوید"
            elif user is None or not user.is_active or PERMISSION not in user.permission_codes:
                sess.revoked_at, sess.revoke_reason = now, "user_disabled"
            else:
                row.used_at = now
                sess.last_seen_at = now
                pair = _issue(s, sess, now)
    if pair is None:
        raise NotAuthenticatedError(reason)
    return pair


def resolve_access(token: str) -> Actor:
    now = utcnow()
    s = new_session()
    try:
        row = s.scalar(
            select(MobileToken).where(
                MobileToken.token_hash == hash_token(token), MobileToken.kind == "access"
            )
        )
        if row is None or _aware(row.expires_at) <= now:
            raise NotAuthenticatedError("توکن منقضی شده است")
        sess = s.get(MobileSession, row.session_id)
        if sess is None or sess.revoked_at is not None or _aware(sess.expires_at) <= now:
            raise NotAuthenticatedError("نشست نامعتبر است؛ دوباره وارد شوید")
        user = s.get(AppUser, sess.user_id)
        if user is None or not user.is_active:
            raise NotAuthenticatedError("حساب کاربری غیرفعال است")
        if now - _aware(sess.last_seen_at) >= _SEEN_EVERY:
            s.execute(
                update(MobileSession).where(MobileSession.id == sess.id).values(last_seen_at=now)
            )
            s.commit()
        return actor_for(user, sess.id)
    finally:
        s.close()


def logout(actor: Actor) -> None:
    with unit_of_work() as s:
        s.execute(
            update(MobileSession)
            .where(MobileSession.id == actor.session_id, MobileSession.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoke_reason="logout")
        )
        audit.record(
            s,
            "auth.mobile_logout",
            user_id=actor.user_id,
            entity_type="mobile_session",
            entity_id=actor.session_id,
        )


def revoke_user(s: Session, user_id: uuid.UUID, reason: str) -> None:
    """Disabling a user or changing their password signs every phone out too."""
    s.execute(
        update(MobileSession)
        .where(MobileSession.user_id == user_id, MobileSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoke_reason=reason)
    )
