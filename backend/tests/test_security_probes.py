"""Attack probes: what an attacker on the shop network would try first (phase 10).

A self-assessment, not a substitute for an independent penetration test
(docs/security/assessment.md).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from tests.conftest import PASSWORD, Api, _settings, make_user, new_key
from tests.test_sales import Pos, login, open_shift, pos, sell  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def test_headers_on_pages_and_api(tmp_path: Path, migrated_db: str | None) -> None:
    assert migrated_db
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>", "utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", "utf-8")
    settings = _settings(migrated_db, static_dir=str(tmp_path)).model_copy(
        update={"cookie_secure": True}
    )
    app = create_app(settings)
    c = app.test_client()
    page = c.get("/pos")
    csp = page.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp
    assert page.headers["X-Frame-Options"] == "DENY"
    assert page.headers["Strict-Transport-Security"].startswith("max-age=")
    assert "camera=()" in page.headers["Permissions-Policy"]
    api = c.get("/api/v1/system/health")
    assert api.headers["Cache-Control"] == "no-store"
    assert api.headers["X-Content-Type-Options"] == "nosniff"
    # Path traversal through the SPA fallback never leaves the build folder.
    for probe in ("/../app/__init__.py", "/assets/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd"):
        r = c.get(probe)
        assert b"import" not in r.data and b"root:" not in r.data, probe


def test_injection_and_markup_are_data(app: Flask, pos: Pos) -> None:  # noqa: F811
    boss = login(app, "boss")
    # SQL injection in search: matched literally, never widens the query.
    r = boss.get("/api/v1/inventory/items?q=%27%20OR%201%3D1%20--")
    assert r.status_code == 200 and r.get_json()["total"] == 0
    r = boss.get("/api/v1/inventory/items/lookup?barcode=1%27%3B%20DROP%20TABLE%20item%3B--")
    assert r.status_code == 404
    assert boss.get("/api/v1/inventory/items").get_json()["total"] >= 4  # still there
    # Markup is stored and returned as text in JSON (React renders it as text).
    unit = boss.get(f"/api/v1/inventory/items/{pos.milk}").get_json()["base_unit_id"]
    xss = "<img src=x onerror=alert(1)>"
    made = boss.post(
        "/api/v1/inventory/items",
        {"code": "XSS1", "name": xss, "base_unit_id": unit},
        idem=new_key(),
    )
    assert made.status_code == 201, made.get_json()
    got = boss.get(f"/api/v1/inventory/items/{made.get_json()['id']}")
    assert got.mimetype == "application/json" and got.get_json()["name"] == xss


def test_request_tampering_is_refused(app: Flask, pos: Pos) -> None:  # noqa: F811
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    body = {
        "id": str(uuid.uuid4()),
        "cash_register_id": pos.r1,
        "lines": [{"item_id": pos.milk, "qty": "1"}],
        "payments": [{"method": "cash", "amount": "110000"}],
    }
    # A field the client may not set (the number, a price) is rejected, not ignored.
    for extra in ({"number": 1}, {"grand_total": "1"}, {"status": "final"}):
        r = c.post("/api/v1/sales/invoices", {**body, **extra}, idem=new_key())
        assert r.status_code == 400, extra
    # A price in the line is not part of the contract either: the server prices.
    tampered = {**body, "lines": [{"item_id": pos.milk, "qty": "1", "unit_price": "1"}]}
    assert c.post("/api/v1/sales/invoices", tampered, idem=new_key()).status_code == 400
    # Money as a JSON number (float) is refused.
    floaty = {**body, "payments": [{"method": "cash", "amount": 110000.0}]}
    assert c.post("/api/v1/sales/invoices", floaty, idem=new_key()).status_code == 400
    # Without the CSRF header a cookie alone does nothing.
    raw = c.c.post("/api/v1/sales/invoices", json=body, headers={"Idempotency-Key": new_key()})
    assert raw.get_json()["error"]["code"] == "csrf_failed"
    # Oversized body.
    big = c.c.post(
        "/api/v1/sales/quote",
        data=b"x" * (3 * 1024 * 1024),
        headers={"Content-Type": "application/json", **c._csrf()},
    )
    assert big.status_code == 413


def test_branch_isolation_on_documents(app: Flask, pos: Pos, seed) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    make_user(app, "sup_a", ["SUP"], [seed.branch_a])
    make_user(app, "sup_b", ["SUP"], [seed.branch_b])
    b = login(app, "sup_b")
    open_shift(b, pos.r_b)
    sale_b = sell(
        b, pos.r_b, [{"item_id": pos.milk, "qty": "1"}], [{"method": "cash", "amount": "110000"}]
    ).get_json()
    a = login(app, "sup_a")
    # Guessing another branch's id gives "not found", never the document.
    assert a.get(f"/api/v1/sales/invoices/{sale_b['id']}").status_code == 404
    returned = a.post(
        f"/api/v1/sales/invoices/{sale_b['id']}/returns",
        {"lines": [], "refunds": [{"method": "cash"}], "reason": "probe"},
        idem=new_key(),
    )
    assert returned.status_code in (400, 404)
    listed = a.get("/api/v1/sales/invoices?page_size=200").get_json()["items"]
    assert sale_b["id"] not in {i["id"] for i in listed}
    assert a.get(f"/api/v1/sales/registers/{pos.r_b}/state").status_code == 404


def test_sessions_and_errors(app: Flask, seed) -> None:  # type: ignore[no-untyped-def]
    make_user(app, "probe", ["CSH"])
    api = Api(app.test_client())
    r = api.login("probe")
    cookie = r.headers.getlist("Set-Cookie")
    session = next(x for x in cookie if x.startswith("nextcam_session="))
    assert "HttpOnly" in session and "SameSite=Lax" in session
    text = r.get_data(as_text=True)
    assert "password_hash" not in text and "$argon2" not in text
    token = session.split(";", 1)[0].split("=", 1)[1]
    assert api.send("POST", "/api/v1/auth/logout", {}).status_code == 200
    # The old cookie is dead after logout (no replay).
    replay = app.test_client()
    replay.set_cookie("nextcam_session", token)
    assert replay.get("/api/v1/auth/me").status_code == 401
    # Wrong password does not say whether the user exists.
    c = app.test_client()
    unknown = c.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    wrong = c.post("/api/v1/auth/login", json={"username": "probe", "password": "wrong"})
    assert unknown.get_json()["error"]["message"] == wrong.get_json()["error"]["message"]
    assert PASSWORD not in wrong.get_data(as_text=True)


def test_internal_errors_do_not_leak(migrated_db: str | None) -> None:
    assert migrated_db
    app = create_app(_settings(migrated_db))

    @app.get("/api/v1/_boom")
    def boom() -> str:
        raise RuntimeError("Server=10.0.0.5;Pwd=hunter2 in C:\\nextcam\\app.py line 42")

    r = app.test_client().get("/api/v1/_boom")
    body = r.get_data(as_text=True)
    assert r.status_code == 500 and "hunter2" not in body and "nextcam\\\\app.py" not in body
    assert r.get_json()["error"]["incident"]
