"""Authentication + authorization for every protected endpoint (ADR-0004).

Hiding a button in the UI is never a control; these checks are.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import ParamSpec, TypeVar

from flask import g, request

from app.core.errors import DomainError, PermissionDeniedError
from app.core.security import hash_token, tokens_equal

P = ParamSpec("P")
R = TypeVar("R")

SESSION_COOKIE = "nextcam_session"
CSRF_COOKIE = "nextcam_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class NotAuthenticatedError(DomainError):
    status_code = 401
    code = "not_authenticated"


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    username: str
    session_id: uuid.UUID
    permissions: frozenset[str]
    # None = all branches
    branch_ids: frozenset[uuid.UUID] | None

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def can_access_branch(self, branch_id: uuid.UUID) -> bool:
        return self.branch_ids is None or branch_id in self.branch_ids


def current_actor() -> Actor:
    actor: Actor | None = g.get("actor")
    if actor is None:
        raise NotAuthenticatedError("ابتدا وارد شوید")
    return actor


def _authenticate() -> Actor:
    from app.modules.iam.services import auth as auth_service

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise NotAuthenticatedError("ابتدا وارد شوید")
    actor, csrf_hash = auth_service.resolve_session(token)
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not tokens_equal(hash_token(sent), csrf_hash):
            raise PermissionDeniedError("توکن CSRF نامعتبر است", code="csrf_failed")
    g.actor = actor
    return actor


def login_required(fn: Callable[P, R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        _authenticate()
        return fn(*args, **kwargs)

    return wrapper


def require(permission: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    from app.modules.iam.permissions import CODES

    if permission not in CODES:
        raise ValueError(f"unknown permission {permission!r}")

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            actor = _authenticate()
            if not actor.has(permission):
                raise PermissionDeniedError("شما مجوز این عملیات را ندارید")
            return fn(*args, **kwargs)

        wrapper.required_permission = permission  # type: ignore[attr-defined]
        return wrapper

    return decorator


def require_any(*permissions: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Read access shared by several roles (e.g. vouchers: preparer, approver, auditor)."""
    from app.modules.iam.permissions import CODES

    unknown = set(permissions) - CODES
    if unknown or not permissions:
        raise ValueError(f"unknown permissions {unknown!r}")

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            actor = _authenticate()
            if not any(actor.has(p) for p in permissions):
                raise PermissionDeniedError("شما مجوز این عملیات را ندارید")
            return fn(*args, **kwargs)

        wrapper.required_permission = " | ".join(permissions)  # type: ignore[attr-defined]
        return wrapper

    return decorator
