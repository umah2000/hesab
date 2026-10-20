from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import func, select

from app.core.db import new_session
from app.modules.iam.models import AppUser
from tests.conftest import PASSWORD, Api, Seed, make_role, make_user, new_key

pytestmark = pytest.mark.db


def _role_id(admin: Api, code: str) -> str:
    roles = admin.get("/api/v1/roles").get_json()
    return next(r["id"] for r in roles if r["code"] == code)


def _user_count(app: Flask) -> int:
    with app.app_context():
        s = new_session()
        try:
            return int(s.scalar(select(func.count()).select_from(AppUser)) or 0)
        finally:
            s.close()


def _new_user(admin: Api, seed: Seed, username: str = "cashier1", **kw: object) -> dict:
    body = {
        "username": username,
        "full_name": "صندوق‌دار یک",
        "password": "Cash1er-pass",
        "role_ids": [_role_id(admin, "CSH")],
        "branch_ids": [str(seed.branch_a)],
        **kw,
    }
    return body


def test_create_user_is_idempotent(app: Flask, admin: Api, seed: Seed) -> None:
    key = new_key()
    body = _new_user(admin, seed)
    first = admin.post("/api/v1/users", body, idem=key)
    assert first.status_code == 201, first.get_json()
    again = admin.post("/api/v1/users", body, idem=key)
    assert again.status_code == 201
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert again.get_json()["id"] == first.get_json()["id"]
    assert _user_count(app) == 2  # admin + one cashier, not two

    changed = admin.post("/api/v1/users", {**body, "full_name": "دیگری"}, idem=key)
    assert changed.status_code == 409
    assert changed.get_json()["error"]["code"] == "idempotency_key_reused"


def test_create_requires_idempotency_key(admin: Api, seed: Seed) -> None:
    resp = admin.post("/api/v1/users", _new_user(admin, seed))
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "idempotency_key_required"


def test_user_validation(admin: Api, seed: Seed) -> None:
    weak = admin.post("/api/v1/users", _new_user(admin, seed, password="12345678"), idem=new_key())
    assert weak.status_code == 422
    assert weak.get_json()["error"]["code"] == "weak_password"
    bad = admin.post("/api/v1/users", {"username": "x"}, idem=new_key())
    assert bad.status_code == 400
    assert bad.get_json()["error"]["code"] == "validation_error"
    admin.post("/api/v1/users", _new_user(admin, seed), idem=new_key())
    dup = admin.post("/api/v1/users", _new_user(admin, seed), idem=new_key())
    assert dup.status_code == 409


def test_persian_text_roundtrips(admin: Api, seed: Seed) -> None:
    created = admin.post(
        "/api/v1/users", _new_user(admin, seed, full_name="زهرا محمدی‌نژاد"), idem=new_key()
    ).get_json()
    fetched = admin.get(f"/api/v1/users/{created['id']}").get_json()
    assert fetched["full_name"] == "زهرا محمدی‌نژاد"


def test_update_requires_current_version(admin: Api, seed: Seed) -> None:
    user = admin.post("/api/v1/users", _new_user(admin, seed), idem=new_key()).get_json()
    url = f"/api/v1/users/{user['id']}"
    missing = admin.patch(url, {"full_name": "نام جدید"}, None)
    assert missing.status_code == 422
    ok = admin.patch(url, {"full_name": "نام جدید"}, user["row_version"])
    assert ok.status_code == 200
    assert ok.get_json()["row_version"] != user["row_version"]
    stale = admin.patch(url, {"full_name": "نام دیگر"}, user["row_version"])
    assert stale.status_code == 409
    assert stale.get_json()["error"]["code"] == "version_conflict"


def test_role_only_change_still_moves_version(admin: Api, seed: Seed) -> None:
    user = admin.post("/api/v1/users", _new_user(admin, seed), idem=new_key()).get_json()
    resp = admin.patch(
        f"/api/v1/users/{user['id']}", {"role_ids": [_role_id(admin, "SUP")]}, user["row_version"]
    )
    assert resp.status_code == 200
    assert resp.get_json()["row_version"] != user["row_version"]


def test_deactivating_user_kills_sessions(app: Flask, admin: Api, seed: Seed) -> None:
    user = admin.post("/api/v1/users", _new_user(admin, seed), idem=new_key()).get_json()
    cashier = Api(app.test_client())
    assert cashier.login("cashier1", "Cash1er-pass").status_code == 200
    assert cashier.get("/api/v1/auth/me").status_code == 200
    # Login touched the row (last_login_at), so the admin works from a fresh copy.
    fresh = admin.get(f"/api/v1/users/{user['id']}").get_json()
    resp = admin.patch(f"/api/v1/users/{user['id']}", {"is_active": False}, fresh["row_version"])
    assert resp.status_code == 200
    assert cashier.get("/api/v1/auth/me").status_code == 401


def test_cannot_deactivate_self_or_remove_last_admin(admin: Api, seed: Seed) -> None:
    me = admin.get(f"/api/v1/users/{seed.admin_id}").get_json()
    self_off = admin.patch(
        f"/api/v1/users/{seed.admin_id}", {"is_active": False}, me["row_version"]
    )
    assert self_off.get_json()["error"]["code"] == "self_deactivate"
    demote = admin.patch(
        f"/api/v1/users/{seed.admin_id}", {"role_ids": [_role_id(admin, "MGR")]}, me["row_version"]
    )
    assert demote.status_code == 422
    assert demote.get_json()["error"]["code"] == "last_admin"


def test_branch_scoped_manager_cannot_escalate(app: Flask, seed: Seed) -> None:
    make_role(app, "BRANCH_ADMIN", ["users.manage"])
    make_user(app, "badmin", ["BRANCH_ADMIN"], [seed.branch_a])
    a = Api(app.test_client())
    assert a.login("badmin").status_code == 200
    roles = a.get("/api/v1/roles").get_json()
    csh = next(r["id"] for r in roles if r["code"] == "CSH")
    base = {
        "username": "cash2",
        "full_name": "صندوق‌دار",
        "password": "Cash1er-pass",
        "role_ids": [csh],
    }
    all_b = a.post("/api/v1/users", {**base, "all_branches": True}, idem=new_key())
    assert all_b.get_json()["error"]["code"] == "scope_escalation"
    other = a.post("/api/v1/users", {**base, "branch_ids": [str(seed.branch_b)]}, idem=new_key())
    assert other.get_json()["error"]["code"] == "scope_escalation"
    own = a.post("/api/v1/users", {**base, "branch_ids": [str(seed.branch_a)]}, idem=new_key())
    assert own.status_code == 201


def test_reset_password_forces_change_and_unlocks(app: Flask, admin: Api, seed: Seed) -> None:
    user = admin.post("/api/v1/users", _new_user(admin, seed), idem=new_key()).get_json()
    resp = admin.post(f"/api/v1/users/{user['id']}/reset-password", {"new_password": "Res3t-pass"})
    assert resp.status_code == 200
    u = Api(app.test_client())
    me = u.login("cashier1", "Res3t-pass").get_json()
    assert me["must_change_password"] is True


def test_admin_role_permissions_are_locked(admin: Api) -> None:
    roles = admin.get("/api/v1/roles").get_json()
    adm = next(r for r in roles if r["code"] == "ADM")
    assert adm["is_locked"] is True
    resp = admin.patch(f"/api/v1/roles/{adm['id']}", {"permissions": []}, adm["row_version"])
    assert resp.get_json()["error"]["code"] == "role_locked"


def test_custom_role_lifecycle(admin: Api) -> None:
    created = admin.post(
        "/api/v1/roles",
        {"code": "night_cashier", "name": "صندوق‌دار شب", "permissions": ["sales.pos.use"]},
        idem=new_key(),
    )
    assert created.status_code == 201, created.get_json()
    role = created.get_json()
    assert role["code"] == "NIGHT_CASHIER"
    upd = admin.patch(
        f"/api/v1/roles/{role['id']}",
        {"permissions": ["sales.pos.use", "sales.shift.open"]},
        role["row_version"],
    )
    assert upd.status_code == 200
    assert upd.get_json()["permissions"] == ["sales.pos.use", "sales.shift.open"]
    bad = admin.patch(
        f"/api/v1/roles/{role['id']}",
        {"permissions": ["root.everything"]},
        upd.get_json()["row_version"],
    )
    assert bad.get_json()["error"]["code"] == "invalid_permission"


def test_permissions_catalog(admin: Api) -> None:
    perms = admin.get("/api/v1/roles/permissions").get_json()
    codes = {p["code"] for p in perms}
    assert {"users.manage", "sales.invoice.void"} <= codes
    assert PASSWORD not in str(perms)
