from __future__ import annotations

from datetime import timedelta

import pytest
from flask import Flask
from sqlalchemy import select, text, update

from app.core.db import new_session, utcnow
from app.core.ratelimit import limiter
from app.modules.audit.models import AuditEvent
from app.modules.iam.guard import CSRF_COOKIE, SESSION_COOKIE
from app.modules.iam.models import UserSession
from app.modules.iam.services.auth import GENERIC_LOGIN_ERROR
from tests.conftest import PASSWORD, Api, Seed, make_user

pytestmark = pytest.mark.db


def _actions(app: Flask) -> list[str]:
    with app.app_context():
        s = new_session()
        try:
            return list(s.scalars(select(AuditEvent.action).order_by(AuditEvent.seq)))
        finally:
            s.close()


def test_login_sets_secure_cookies_and_returns_permissions(api: Api, seed: Seed) -> None:
    resp = api.login("admin")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["username"] == "admin"
    assert "users.manage" in body["permissions"]
    assert body["all_branches"] is True
    cookies = resp.headers.getlist("Set-Cookie")
    session_cookie = next(c for c in cookies if c.startswith(SESSION_COOKIE))
    csrf_cookie = next(c for c in cookies if c.startswith(CSRF_COOKIE))
    assert "HttpOnly" in session_cookie and "SameSite=Lax" in session_cookie
    assert "HttpOnly" not in csrf_cookie


def test_wrong_password_and_unknown_user_look_identical(api: Api, seed: Seed) -> None:
    bad = api.login("admin", "wrong-pass1")
    unknown = api.login("nobody", "wrong-pass1")
    assert bad.status_code == unknown.status_code == 401
    assert bad.get_json() == unknown.get_json()
    assert bad.get_json()["error"]["message"] == GENERIC_LOGIN_ERROR


def test_lockout_after_repeated_failures(app: Flask, api: Api, seed: Seed) -> None:
    make_user(app, "cashier1", ["CSH"])
    for _ in range(5):
        assert api.login("cashier1", "wrong-pass1").status_code == 401
    # Correct password is refused while locked.
    assert api.login("cashier1", PASSWORD).status_code == 401
    actions = _actions(app)
    assert "auth.user_locked" in actions
    # Expire the lock -> login works again.
    with app.app_context():
        s = new_session()
        s.execute(
            text(
                "UPDATE app_user SET locked_until = DATEADD(minute, -1, SYSUTCDATETIME())"
                " WHERE username = 'cashier1'"
            )
        )
        s.commit()
        s.close()
    assert api.login("cashier1", PASSWORD).status_code == 200


def test_inactive_user_cannot_login(app: Flask, api: Api, seed: Seed) -> None:
    make_user(app, "gone", ["CSH"], active=False)
    assert api.login("gone").status_code == 401


def test_protected_endpoint_requires_session(api: Api, seed: Seed) -> None:
    resp = api.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "not_authenticated"


def test_state_changing_request_requires_csrf(admin: Api) -> None:
    no_header = admin.c.post("/api/v1/auth/logout")
    assert no_header.status_code == 403
    assert no_header.get_json()["error"]["code"] == "csrf_failed"
    forged = admin.c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert forged.status_code == 403
    assert admin.post("/api/v1/auth/logout").status_code == 200


def test_logout_revokes_session(admin: Api) -> None:
    assert admin.get("/api/v1/auth/me").status_code == 200
    assert admin.post("/api/v1/auth/logout").status_code == 200
    # Replaying the old cookie must not work either.
    assert admin.get("/api/v1/auth/me").status_code == 401


def test_idle_session_expires(app: Flask, admin: Api) -> None:
    with app.app_context():
        s = new_session()
        s.execute(update(UserSession).values(last_seen_at=utcnow() - timedelta(hours=5)))
        s.commit()
        s.close()
    assert admin.get("/api/v1/auth/me").status_code == 401


def test_change_password(app: Flask, admin: Api) -> None:
    other = Api(app.test_client())
    assert other.login("admin").status_code == 200

    wrong = admin.post(
        "/api/v1/auth/change-password",
        {"current_password": "nope-123", "new_password": "N3w-password"},
    )
    assert wrong.status_code == 422
    weak = admin.post(
        "/api/v1/auth/change-password", {"current_password": PASSWORD, "new_password": "short"}
    )
    assert weak.status_code == 422
    ok = admin.post(
        "/api/v1/auth/change-password",
        {"current_password": PASSWORD, "new_password": "N3w-password"},
    )
    assert ok.status_code == 200
    # This session stays, other sessions are revoked.
    assert admin.get("/api/v1/auth/me").status_code == 200
    assert other.get("/api/v1/auth/me").status_code == 401
    assert Api(app.test_client()).login("admin", "N3w-password").status_code == 200


def test_login_rate_limited(app: Flask, seed: Seed) -> None:
    app.config["SETTINGS"].login_rate_limit = "3 per minute"
    limiter.enabled = True
    limiter.reset()
    try:
        a = Api(app.test_client())
        codes = [a.login(f"u{i}", "wrong-pass1").status_code for i in range(4)]
        assert codes[:3] == [401, 401, 401]
        assert codes[3] == 429
    finally:
        limiter.enabled = False
        limiter.reset()


def test_audit_never_contains_password(app: Flask, api: Api, seed: Seed) -> None:
    api.login("admin", "Secret-Value-99")
    api.login("admin")
    with app.app_context():
        s = new_session()
        rows = list(s.scalars(select(AuditEvent.data)))
        s.close()
    assert all("Secret-Value-99" not in (r or "") for r in rows)
    assert all(PASSWORD not in (r or "") for r in rows)
