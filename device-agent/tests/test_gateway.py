"""Register gateway: proxy, page cache, offline selling and sync — against a fake server
that can be switched off mid-test (a real outage on a loopback port)."""

from __future__ import annotations

import contextlib
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from nextcam_agent.client import ServerClient
from nextcam_agent.gateway import Gateway, Reply, make_server
from nextcam_agent.store import Store
from nextcam_agent.syncer import Local, Syncer

USER = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
REG = str(uuid.uuid4())
BRANCH = str(uuid.uuid4())
SHIFT = str(uuid.uuid4())
PCS = str(uuid.uuid4())
PACK = str(uuid.uuid4())
KG = str(uuid.uuid4())
MILK = str(uuid.uuid4())
WATER = str(uuid.uuid4())
CHEESE = str(uuid.uuid4())
PORT = 47699
HOST = {"Host": f"127.0.0.1:{PORT}"}
ME = {
    "id": USER,
    "username": "cashier",
    "full_name": "صندوق‌دار یک",
    "must_change_password": False,
    "roles": [],
    "permissions": ["sales.pos.use"],
    "all_branches": False,
    "branch_ids": [BRANCH],
    "session_expires_at": (datetime.now(UTC) + timedelta(hours=8)).isoformat(),
}


def item(i: str, code: str, name: str, unit: str, **kw: Any) -> dict[str, Any]:
    return {
        "id": i,
        "code": code,
        "name": name,
        "group_id": None,
        "base_unit_id": unit,
        "item_type": "goods",
        "is_weighted": False,
        "scale_code": None,
        "vat_exempt": False,
        "vat_rate": None,
        "stock": "10.000",
        **kw,
    }


def snapshot(**kw: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    snap = {
        "version": "v1",
        "generated_at": now.isoformat(),
        "valid_until": (now + timedelta(hours=24)).isoformat(),
        "number_prefix": "AB12CD34",
        "cash_register": {
            "id": REG,
            "code": "R1",
            "name": "صندوق ۱",
            "branch_id": BRANCH,
            "branch_name": "مرکزی",
            "warehouse_id": str(uuid.uuid4()),
        },
        "shift": {
            "id": SHIFT,
            "user_id": USER,
            "username": "cashier",
            "user_name": "صندوق‌دار یک",
            "opened_at": (now - timedelta(hours=1)).isoformat(),
            "opening_cash": "0.0000",
            "permissions": ["sales.payment.card", "sales.payment.cash", "sales.pos.use"],
        },
        "settings": {
            "organization_name": "سوپرمارکت آزمایشی",
            "timezone": "Asia/Tehran",
            "display_currency": "IRT",
            "default_vat_rate": "10",
            "prices_include_vat": False,
            "cashier_discount_limit": "0",
            "negative_stock_policy": "warn",
            "receipt_header": None,
            "receipt_footer": "سپاس",
        },
        "units": [
            {"id": PCS, "name": "عدد", "allows_fraction": False},
            {"id": PACK, "name": "بسته", "allows_fraction": False},
            {"id": KG, "name": "کیلوگرم", "allows_fraction": True},
        ],
        "items": [
            item(MILK, "M1", "شیر", PCS),
            item(WATER, "W1", "آب معدنی", PCS),
            item(CHEESE, "CH", "پنیر", KG, is_weighted=True, scale_code="00201", vat_exempt=True),
        ],
        "factors": [{"item_id": WATER, "unit_id": PACK, "factor": "6"}],
        "prices": [
            {"item_id": MILK, "unit_id": PCS, "price": "110000.0000"},
            {"item_id": WATER, "unit_id": PCS, "price": "15000.0000"},
            {"item_id": CHEESE, "unit_id": KG, "price": "3900000.0000"},
        ],
        "barcodes": [
            {"barcode": "6261000000016", "item_id": MILK, "unit_id": None},
            {"barcode": "6261000000023", "item_id": WATER, "unit_id": PACK},
        ],
        "scale_rules": [
            {"prefix": "21", "item_code_length": 5, "value_type": "weight", "value_decimals": 3}
        ],
        "promotions": [],
    }
    snap.update(kw)
    return snap


class Upstream:
    """A stand-in for the NEXTCAM server, enough to watch what the gateway sends."""

    def __init__(self) -> None:
        self.snap = snapshot()
        self.pushed: list[dict[str, Any]] = []
        self.seen: list[tuple[str, str, dict[str, str]]] = []
        self.srv: ThreadingHTTPServer | None = None
        self.port = 0

    def start(self) -> None:
        up = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, status: int, body: bytes, ctype: str, *extra: tuple[str, str]) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, data: Any, *extra: tuple[str, str]) -> None:
                self._send(status, json.dumps(data).encode(), "application/json", *extra)

            def do_GET(self) -> None:
                up.seen.append(("GET", self.path, dict(self.headers.items())))
                if self.path in ("/", "/pos"):
                    self._send(200, b"<html>POS</html>", "text/html; charset=utf-8")
                elif self.path == "/assets/app-1.js":
                    self._send(200, b"console.log(1)", "text/javascript")
                elif self.path == "/api/v1/auth/me":
                    self._json(200, ME)
                elif self.path == "/api/v1/sync/agent/snapshot":
                    tag = f'"{up.snap["version"]}"'
                    if self.headers.get("If-None-Match") == tag:
                        self._send(304, b"", "application/json", ("ETag", tag))
                    else:
                        self._json(200, up.snap, ("ETag", tag))
                else:
                    self._json(404, {"error": {"code": "not_found", "message": "x"}})

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                up.seen.append(("POST", self.path, dict(self.headers.items())))
                if self.path == "/api/v1/auth/login":
                    self._json(
                        200,
                        ME,
                        (
                            "Set-Cookie",
                            "nextcam_session=tok-1; Path=/; HttpOnly; Secure; SameSite=Lax",
                        ),
                        ("Set-Cookie", "nextcam_csrf=csrf-1; Path=/; Secure; SameSite=Lax"),
                    )
                elif self.path == "/api/v1/sync/agent/push":
                    ops = json.loads(body)["ops"]
                    up.pushed += ops
                    self._json(
                        200,
                        {
                            "results": [
                                {
                                    "id": o["id"],
                                    "status": "applied",
                                    "code": None,
                                    "message": None,
                                    "invoice_id": o["id"],
                                    "number": n,
                                }
                                for n, o in enumerate(ops, start=len(up.pushed) - len(ops) + 1)
                            ]
                        },
                    )
                else:
                    self._json(200, {"from": "server", "path": self.path})

        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self) -> None:
        assert self.srv is not None
        self.srv.shutdown()
        self.srv.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture
def env(tmp_path: Path):  # type: ignore[no-untyped-def]
    up = Upstream()
    up.start()
    store = Store(tmp_path / "register.db")
    local = Local(store)
    printed: list[dict[str, Any]] = []

    def print_fn(job: dict[str, Any], printer: dict[str, Any]) -> tuple[bool, str | None]:
        printed.append(job)
        return True, None

    gw = Gateway(up.url, local, tmp_path / "spa", port=PORT, device_id="dev-1", print_fn=print_fn)
    client = ServerClient(up.url, "device-token")
    syncer = Syncer(local, client)
    yield up, gw, local, syncer, printed
    store.close()
    with contextlib.suppress(AssertionError, OSError):
        up.stop()


COOKIE = {"Cookie": "nextcam_session=tok-1; nextcam_csrf=csrf-1"}


def call(gw: Gateway, method: str, path: str, body: Any = None, **headers: str) -> Reply:
    h = {**HOST, **COOKIE, **headers}
    if method != "GET":
        h.setdefault("X-CSRF-Token", "csrf-1")
        h.setdefault("Origin", f"http://127.0.0.1:{PORT}")
    data = json.dumps(body).encode() if body is not None else b""
    return gw.handle(method, path, h, data)


def js(r: Reply) -> Any:
    return json.loads(r.body)


def hdr(r: Reply, name: str) -> list[str]:
    return [v for k, v in r.headers if k.lower() == name.lower()]


def go_offline(up: Upstream, gw: Gateway) -> None:
    up.stop()
    r = call(gw, "GET", "/api/v1/auth/me")  # first failure flips the gateway to offline
    assert hdr(r, "X-Nextcam-Mode") == ["offline"]


def cart(*lines: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {"cash_register_id": REG, "lines": list(lines), **kw}


def test_online_proxy_session_and_page_cache(env) -> None:  # type: ignore[no-untyped-def]
    up, gw, local, syncer, _ = env
    login = call(gw, "POST", "/api/v1/auth/login", {"username": "cashier", "password": "x"})
    assert login.status == 200 and hdr(login, "X-Nextcam-Mode") == ["online"]
    cookies = hdr(login, "Set-Cookie")
    assert len(cookies) == 2 and not any("Secure" in c for c in cookies)
    assert local.store.session(__import__("hashlib").sha256(b"tok-1").hexdigest()) is not None
    # Headers the server needs reach it; the cookie and CSRF token included.
    q = call(gw, "POST", "/api/v1/sales/quote", cart(), **{"Idempotency-Key": "k1"})
    assert js(q) == {"from": "server", "path": "/api/v1/sales/quote"}
    sent = {k.lower(): v for k, v in up.seen[-1][2].items()}
    assert sent["x-csrf-token"] == "csrf-1" and sent["idempotency-key"] == "k1"
    assert "tok-1" in sent["cookie"]
    # Pages are kept for a reload while offline.
    assert call(gw, "GET", "/").body == b"<html>POS</html>"
    assert call(gw, "GET", "/assets/app-1.js").status == 200
    syncer.pull()
    up.stop()
    assert call(gw, "GET", "/pos").body == b"<html>POS</html>"  # SPA route → index.html
    assert call(gw, "GET", "/assets/app-1.js").body == b"console.log(1)"
    assert call(gw, "GET", "/assets/missing.js").status == 503


def test_guards(env) -> None:  # type: ignore[no-untyped-def]
    _, gw, *_ = env
    assert gw.handle("GET", "/", {"Host": "evil.example:47699"}, b"").status == 403
    foreign = call(gw, "POST", "/api/v1/sales/quote", cart(), Origin="http://evil.example")
    assert foreign.status == 403
    site = call(gw, "POST", "/api/v1/sales/quote", cart(), **{"Sec-Fetch-Site": "cross-site"})
    assert site.status == 403
    assert call(gw, "POST", "/local/status").status == 405


def test_offline_selling_with_the_shared_pricing_core(env) -> None:  # type: ignore[no-untyped-def]
    up, gw, local, syncer, printed = env
    call(gw, "GET", "/api/v1/auth/me")  # the server vouches for this browser session
    syncer.pull()
    local.store.put_json(
        "printer",
        {
            "transport": "tcp",
            "address": "x",
            "paper_width": 80,
            "cut_paper": True,
            "drawer_enabled": True,
            "drawer_pin": 2,
        },
    )
    go_offline(up, gw)

    assert js(call(gw, "GET", "/api/v1/auth/me"))["id"] == USER
    state = js(call(gw, "GET", f"/api/v1/sales/registers/{REG}/state"))
    assert state["shift"]["id"] == SHIFT and state["held_count"] == 0
    assert "sales.payment.credit" not in state["permissions"]
    # Scanning: product barcode, pack barcode and a scale label (0.750 kg of cheese).
    assert (
        js(call(gw, "GET", "/api/v1/inventory/items/lookup?barcode=6261000000016"))["item_id"]
        == MILK
    )
    pack = js(call(gw, "GET", "/api/v1/inventory/items/lookup?barcode=6261000000023"))
    assert (pack["source"], pack["unit_id"], pack["unit_price"]) == (
        "pack_barcode",
        PACK,
        "90000.0000",
    )
    label = "2100201007506"
    scale = js(call(gw, "GET", f"/api/v1/inventory/items/lookup?barcode={label}"))
    assert (scale["item_id"], scale["qty"], scale["source"]) == (CHEESE, "0.750", "scale_weight")
    assert call(gw, "GET", "/api/v1/inventory/items/lookup?barcode=999").status == 404
    found = js(call(gw, "GET", "/api/v1/inventory/items?q=%D8%B4%DB%8C%D8%B1&page_size=12"))
    assert [i["id"] for i in found["items"]] == [MILK]

    lines = [
        {"item_id": MILK, "qty": "2"},
        {"item_id": WATER, "qty": "1", "unit_id": PACK},
        {"item_id": CHEESE, "qty": "1", "barcode": label},
    ]
    quote = js(call(gw, "POST", "/api/v1/sales/quote", cart(*lines)))
    # VAT-exclusive: milk 220 000 + 22 000, water pack 90 000 + 9 000, cheese 2 925 000 exempt.
    assert (quote["subtotal"], quote["tax_total"], quote["grand_total"]) == (
        "3235000.0000",
        "31000.0000",
        "3266000.0000",
    )
    sale_id = str(uuid.uuid4())
    body = cart(
        *lines,
        id=sale_id,
        payments=[{"method": "cash", "amount": "3266000"}],
        cash_tendered="3300000",
    )
    r = call(gw, "POST", "/api/v1/sales/invoices", body)
    assert r.status == 201, r.body
    inv = js(r)
    assert (inv["device_number"], inv["number"], inv["offline"]) == ("AB12CD34-1", None, True)
    assert inv["change_due"] == "34000.0000" and inv["cashier_name"] == "صندوق‌دار یک"
    assert hdr(r, "X-Nextcam-Queue") == ["1"]
    # The same cart id again (a double click, a retry) is the same sale.
    assert js(call(gw, "POST", "/api/v1/sales/invoices", body))["device_number"] == "AB12CD34-1"
    assert local.store.pending_count() == 1
    # Local stock follows the offline sales.
    milk = js(call(gw, "GET", "/api/v1/inventory/items?q=M1"))["items"][0]
    assert milk["stock_qty"] == "8.000"

    # Receipt and drawer on the register's own printer: the drawer opens once.
    job = js(call(gw, "POST", "/api/v1/devices/print-receipt", {"invoice_id": sale_id}))
    assert job["status"] == "done"
    pl = printed[-1]["payload"]
    assert ["شماره صندوق", "AB12CD34-1"] in pl["meta"] and pl["open_drawer"] is True
    assert any("آفلاین" in n for n in pl["notes"])
    assert js(call(gw, "GET", f"/api/v1/devices/jobs/{job['id']}"))["status"] == "done"
    call(gw, "POST", "/api/v1/devices/print-receipt", {"invoice_id": sale_id})
    assert printed[-1]["payload"]["open_drawer"] is False
    assert printed[-1]["payload"]["heading"].endswith("(چاپ مجدد)")

    # What needs the server says so instead of pretending.
    credit = call(
        gw,
        "POST",
        "/api/v1/sales/invoices",
        cart(lines[0], id=str(uuid.uuid4()), payments=[{"method": "credit", "amount": "242000"}]),
    )
    assert js(credit)["error"]["code"] == "offline_unsupported"
    no_ref = call(
        gw,
        "POST",
        "/api/v1/sales/invoices",
        cart(lines[0], id=str(uuid.uuid4()), payments=[{"method": "card", "amount": "242000"}]),
    )
    assert js(no_ref)["error"]["code"] == "card_reference_required"
    held = call(gw, "POST", "/api/v1/sales/held", cart(*lines))
    assert held.status == 503 and js(held)["error"]["code"] == "offline"
    assert call(gw, "POST", "/api/v1/auth/login", {}).status == 503
    removal = call(
        gw,
        "POST",
        "/api/v1/sales/line-removals",
        {"cash_register_id": REG, "item_id": MILK, "qty": "1", "line_total": "121000"},
    )
    assert removal.status == 201

    # No CSRF token, unknown browser, another user: refused.
    assert (
        call(gw, "POST", "/api/v1/sales/quote", cart(*lines), **{"X-CSRF-Token": "nope"}).status
        == 403
    )
    stranger = gw.handle("GET", "/api/v1/auth/me", {**HOST, "Cookie": "nextcam_session=other"}, b"")
    assert stranger.status == 401

    status = js(call(gw, "GET", "/local/status"))
    assert status["mode"] == "offline" and status["can_sell_offline"] is True
    assert status["queue"]["pending"] == 2  # the sale and the line removal

    # Back online: the queue goes up in order, once.
    up.start()
    syncer.step()
    assert [o["type"] for o in up.pushed] == ["sale", "line_removal"]
    sale_op = up.pushed[0]["sale"]
    assert sale_op["device_number"] == "AB12CD34-1" and sale_op["grand_total"] == "3266000.0000"
    assert sale_op["prices_include_vat"] is False and sale_op["user_id"] == USER
    assert local.store.pending_count() == 0
    rows = js(call(gw, "GET", "/local/sales"))
    assert {(r["kind"], r["status"]) for r in rows} == {
        ("sale", "applied"),
        ("line_removal", "applied"),
    }
    syncer.step()
    assert len(up.pushed) == 2  # nothing is sent twice


def test_offline_needs_a_fresh_snapshot_and_the_shift_owner(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    up, gw, local, _syncer, _ = env
    call(gw, "GET", "/api/v1/auth/me")
    go_offline(up, gw)
    none = call(gw, "GET", f"/api/v1/sales/registers/{REG}/state")
    assert none.status == 503 and js(none)["error"]["code"] == "offline_unavailable"

    old = snapshot(valid_until=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    local.set_snapshot(old, '"v1"', datetime.now(UTC).isoformat())
    assert (
        js(call(gw, "POST", "/api/v1/sales/quote", cart()))["error"]["code"]
        == "offline_unavailable"
    )

    other = snapshot(shift={**snapshot()["shift"], "user_id": OTHER})
    local.set_snapshot(other, '"v2"', datetime.now(UTC).isoformat())
    r = call(
        gw,
        "POST",
        "/api/v1/sales/invoices",
        cart(
            {"item_id": MILK, "qty": "1"},
            id=str(uuid.uuid4()),
            payments=[{"method": "cash", "amount": "121000"}],
        ),
    )
    assert js(r)["error"]["code"] == "no_open_shift"


def test_socket_server_end_to_end(env) -> None:  # type: ignore[no-untyped-def]
    import http.client

    _, gw, *_ = env
    srv = make_server(gw)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        c.request("GET", "/local/status")
        r = c.getresponse()
        assert r.status == 200 and json.loads(r.read())["mode"] in ("online", "offline")
        c.request("OPTIONS", "/api/v1/sales/quote", headers={"Origin": "http://evil.example"})
        r = c.getresponse()
        r.read()
        assert r.status == 405 and r.getheader("Access-Control-Allow-Origin") is None
    finally:
        srv.shutdown()
        srv.server_close()


def test_queued_sales_survive_a_restart(env, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    up, gw, local, syncer, _ = env
    call(gw, "GET", "/api/v1/auth/me")
    syncer.pull()
    go_offline(up, gw)
    sale_id = str(uuid.uuid4())
    body = cart(
        {"item_id": MILK, "qty": "1"}, id=sale_id, payments=[{"method": "cash", "amount": "121000"}]
    )
    assert call(gw, "POST", "/api/v1/sales/invoices", body).status == 201
    local.store.close()  # power cut: only what is on disk is left

    store = Store(tmp_path / "register.db")
    try:
        again = Local(store)
        assert store.pending_count() == 1 and store.op(sale_id) is not None
        snap = again.snapshot()
        assert snap is not None and snap.stock(MILK) == Decimal("9.000")
        nxt = Gateway(up.url, again, tmp_path / "spa", port=PORT)
        nxt.local.server_down("still down")
        second = js(call(nxt, "POST", "/api/v1/sales/invoices", dict(body, id=str(uuid.uuid4()))))
        assert second["device_number"] == "AB12CD34-2"  # the sequence continues, never repeats
    finally:
        store.close()
