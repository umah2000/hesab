"""Fuzzing every route (security pass of 1405/08): hostile input on each GET route's
filters and on each write route's body must give a clean 4xx or an ordinary answer —
never a 500, never a database or Python detail, never a delay that shows SQL ran.

Routes come from the app's own URL map, so a route added later is fuzzed too.
"""

from __future__ import annotations

import time
import uuid

import pytest
from flask import Flask

from tests.test_sales import Pos, login, pos  # noqa: F401 - fixture

pytestmark = pytest.mark.db

# Text filters (searched with LIKE or compared) and the kinds of value they get.
TEXT_PARAMS = ("q", "number", "barcode", "code", "status", "kind", "group_by", "format", "method")
TYPED_PARAMS = (
    "page", "page_size", "date_from", "date_to", "days", "item_id", "warehouse_id",
    "branch_id", "account_id", "fiscal_year_id", "party_id", "customer_id", "register_id",
)  # fmt: skip
PAYLOADS = [
    "' OR 1=1--",
    "1' OR '1'='1",
    "'; DROP TABLE item;--",
    "1; WAITFOR DELAY '0:0:3'--",
    "1' WAITFOR DELAY '0:0:3'--",
    "') UNION SELECT name, password_hash FROM app_user--",
    "%",
    "_",
    "[a-z]%",
    "<script>alert(1)</script>",
    "../../../../etc/passwd",
    "\x00",
    "‮gnp.exe",
    "9" * 60,
    "-1",
    "1e309",
    "NaN",
    "2026-13-45",
    "ي" * 3000,
]
LEAKS = ("pyodbc", "sqlalchemy", "Traceback", "SQL Server", "ODBC", 'File "', "password_hash")
BODIES: list[object] = [
    {},
    [],
    "x",
    123,
    None,
    {"id": "' OR 1=1--", "name": "' OR 1=1--", "code": "<script>", "amount": 1e309},
    {"amount": 110000.5, "qty": float("1e300")},
    {"lines": [{"item_id": "../../etc/passwd", "qty": "1' OR '1'='1"}]},
]


def _routes(app: Flask, methods: set[str]) -> list[tuple[str, str]]:
    out = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1/") or "_boom" in rule.rule:
            continue
        for m in sorted((rule.methods or set()) & methods):
            path = rule.rule
            for arg in rule.arguments:
                path = path.replace(f"<{arg}>", str(uuid.uuid4()))
                path = path.replace(f"<uuid:{arg}>", str(uuid.uuid4()))
                path = path.replace(f"<path:{arg}>", "x")
                path = path.replace(f"<int:{arg}>", "1")
            out.append((m, path))
    return out


def _check(r, what: str) -> None:  # type: ignore[no-untyped-def]
    assert r.status_code < 500, (what, r.status_code, r.get_data()[:300])
    if not (r.mimetype or "").startswith(("application/json", "text/")):
        return  # images, Excel, the compressed search index: no text to leak into
    body = r.get_data(as_text=True)
    for leak in LEAKS:
        assert leak not in body, (what, leak)


def test_every_get_route_survives_hostile_filters(app: Flask, pos: Pos) -> None:  # noqa: F811
    boss = login(app, "boss")
    routes = _routes(app, {"GET"})
    assert len(routes) > 100
    slow: list[str] = []
    for _m, path in routes:
        for payload in PAYLOADS:
            for names in (TEXT_PARAMS, TYPED_PARAMS):
                t = time.perf_counter()
                r = boss.c.get(path, query_string={n: payload for n in names})
                took = time.perf_counter() - t
                _check(r, f"GET {path} {names[0]}={payload[:30]!r}")
                if "WAITFOR" in payload and took > 2.5:
                    slow.append(f"{path} {took:.1f}s")
    # A WAITFOR that reached SQL Server would hold the request for 3 seconds.
    assert not slow, slow


def test_every_write_route_survives_hostile_bodies(app: Flask, pos: Pos) -> None:  # noqa: F811
    boss = login(app, "boss")
    routes = _routes(app, {"POST", "PUT", "PATCH", "DELETE"})
    assert len(routes) > 80
    for method, path in routes:
        if path.endswith(("/auth/logout", "/auth/login")):
            continue  # logging out mid-test ends the session; login has its own tests
        for body in BODIES:
            r = boss.c.open(
                path,
                method=method,
                json=body,
                headers={**boss._csrf(), "Idempotency-Key": str(uuid.uuid4()), "If-Match": "00"},
            )
            _check(r, f"{method} {path} {str(body)[:40]}")
        # A deeply nested document (parser recursion) and broken JSON.
        for raw in (b"[" * 50_000 + b"]" * 50_000, b'{"a": ', b"\xff\xfe"):
            r = boss.c.open(
                path,
                method=method,
                data=raw,
                headers={**boss._csrf(), "Content-Type": "application/json", "If-Match": "00"},
            )
            _check(r, f"{method} {path} raw {raw[:10]!r}")


def test_login_survives_hostile_credentials(app: Flask, pos: Pos) -> None:  # noqa: F811
    c = app.test_client()
    for payload in ("' OR 1=1--", "admin'--", "boss' OR '1'='1", "\x00", "ي" * 5000, "%", "_"):
        r = c.post("/api/v1/auth/login", json={"username": payload, "password": payload})
        _check(r, f"login {payload[:20]!r}")
        assert r.status_code in (400, 401, 429), (payload, r.status_code)
        assert c.get("/api/v1/auth/me").status_code == 401
