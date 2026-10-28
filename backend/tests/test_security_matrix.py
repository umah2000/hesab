"""Every protected endpoint must refuse callers that lack its permission or a session."""

from __future__ import annotations

import uuid

import pytest
from flask import Flask
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import new_session
from tests.conftest import Api, Seed, make_role, make_user, new_key

pytestmark = pytest.mark.db


def _protected_routes(app: Flask) -> list[tuple[str, str, str]]:
    out = []
    for rule in app.url_map.iter_rules():
        perm = getattr(app.view_functions[rule.endpoint], "required_permission", None)
        if not perm:
            continue
        path = rule.rule
        for arg in rule.arguments:
            path = path.replace(f"<{arg}>", str(uuid.uuid4()))
        for method in (rule.methods or set()) - {"HEAD", "OPTIONS"}:
            out.append((method, path, perm))
    return out


def test_every_permission_guarded_route_returns_403_without_permission(
    app: Flask, seed: Seed
) -> None:
    make_role(app, "NOTHING", [])
    make_user(app, "plain", ["NOTHING"])
    a = Api(app.test_client())
    assert a.login("plain").status_code == 200
    routes = _protected_routes(app)
    assert len(routes) >= 12
    for method, path, perm in routes:
        resp = a.send(method, path, {}, {"Idempotency-Key": new_key(), "If-Match": "00"})
        assert resp.status_code == 403, (method, path, perm, resp.get_json())


def test_every_api_route_requires_session_except_public(app: Flask, seed: Seed) -> None:
    public = {
        "/api/v1/system/health",
        "/api/v1/system/ready",
        "/api/v1/openapi.json",
        "/api/v1/auth/login",
        # Device Agents authenticate with a one-time pairing code (rate-limited).
        "/api/v1/devices/agent/pair",
        # The visitor app signs in with a password or a refresh token (rate-limited).
        "/api/v1/auth/mobile/login",
        "/api/v1/auth/mobile/refresh",
        # The login page shows the shop's name and logo (nothing else, ADR-0022).
        "/api/v1/system/branding",
        "/api/v1/system/logo",
        # The weighbridge platform signs each request (HMAC); tested in test_integrations.
        "/api/v1/integrations/va/webhook",
    }
    c = app.test_client()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/") or rule.rule in public:
            continue
        path = rule.rule
        for arg in rule.arguments:
            path = path.replace(f"<{arg}>", str(uuid.uuid4()))
        for method in (rule.methods or set()) - {"HEAD", "OPTIONS"}:
            resp = c.open(path, method=method, json={})
            assert resp.status_code == 401, (method, path)


def test_branch_scope_isolation(app: Flask, seed: Seed) -> None:
    make_role(app, "VIEWER", ["sales.pos.use"])
    make_user(app, "a_only", ["VIEWER"], [seed.branch_a])
    a = Api(app.test_client())
    a.login("a_only")
    branches = a.get("/api/v1/organization/branches").get_json()
    assert [b["code"] for b in branches] == ["01"]
    other = a.get(f"/api/v1/organization/branches/{seed.branch_b}/cash-registers")
    assert other.status_code == 404


def test_audit_log_is_append_only_in_database(app: Flask, admin: Api) -> None:
    with app.app_context():
        s = new_session()
        try:
            with pytest.raises(DBAPIError, match="append-only"):
                s.execute(text("UPDATE audit_event SET action = 'tampered'"))
            s.rollback()
            with pytest.raises(DBAPIError, match="append-only"):
                s.execute(text("DELETE FROM audit_event"))
        finally:
            s.rollback()
            s.close()


def test_openapi_lists_permissions(client: object, seed: Seed, app: Flask) -> None:
    spec = app.test_client().get("/api/v1/openapi.json").get_json()
    op = spec["paths"]["/api/v1/users"]["post"]
    assert op["x-required-permission"] == "users.manage"
    assert any(p["name"] == "Idempotency-Key" for p in op["parameters"])
