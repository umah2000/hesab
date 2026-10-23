"""Protocol-level tests. They prove the bytes and the behaviour, not a printer model."""

from __future__ import annotations

import http.client
import socket
import threading
from typing import Any

import pytest
from PIL import Image, ImageChops

from nextcam_agent import escpos, render, transports
from nextcam_agent.client import Unauthorized
from nextcam_agent.config import AgentConfig
from nextcam_agent.localapi import make_server
from nextcam_agent.render import receipt_image
from nextcam_agent.runner import Agent

PAYLOAD: dict[str, Any] = {
    "title": "سوپرمارکت آزمایشی",
    "header": ["خیابان آزادی، پلاک ۱۲"],
    "heading": "فاکتور فروش",
    "meta": [["شماره", "۱۲"], ["تاریخ", "۱۴۰۵/۰۷/۲۳  ۱۰:۱۵"]],
    "lines": [
        {"name": "شیر پرچرب ۱ لیتری", "detail": "۲ عدد × ۱۱٬۰۰۰", "amount": "۲۲٬۰۰۰"},
        {"name": "نان بربری *", "detail": "۱ عدد × ۵٬۰۰۰", "amount": "۵٬۰۰۰"},
    ],
    "totals": [
        {"label": "جمع", "value": "۲۷٬۰۰۰", "bold": False},
        {"label": "قابل پرداخت", "value": "۲۷٬۰۰۰ تومان", "bold": True},
    ],
    "notes": ["* کالای معاف از مالیات"],
    "footer": ["از خرید شما سپاسگزاریم"],
    "open_drawer": True,
    "cut": True,
}
PRINTER = {
    "transport": "tcp",
    "address": "127.0.0.1:9100",
    "paper_width": 80,
    "cut_paper": True,
    "drawer_enabled": True,
    "drawer_pin": 2,
}


# --- ESC/POS ---------------------------------------------------------------------


def test_raster_round_trip_and_bands() -> None:
    img = Image.new("1", (570, 600), 1)
    img.paste(0, (10, 10, 100, 590))
    data = escpos.raster(img)
    # 600 rows → bands of 255 + 255 + 90; width padded to whole bytes (72 bytes = 576 dots).
    assert data.count(b"\x1dv0\x00") == 3
    assert data[4:8] == bytes([72, 0, 255, 0])
    back = escpos.decode_raster(data)
    assert [b.height for b in back] == [255, 255, 90]
    joined = Image.new("1", (576, 600), 1)
    y = 0
    for b in back:
        joined.paste(b, (0, y))
        y += b.height
    assert (
        ImageChops.difference(
            joined.crop((0, 0, 570, 600)).convert("L"), img.convert("L")
        ).getbbox()
        is None
    )


def test_job_bytes_drawer_cut_order() -> None:
    img = Image.new("1", (576, 10), 1)
    data = escpos.receipt_bytes(img, cut_paper=True, drawer_pin=5)
    assert data.startswith(b"\x1b@\x1bp\x01\x19\xfa")  # init, then drawer pin 5 (m=1)
    assert data.endswith(b"\x1bd\x04\x1dVB\x00")  # feed 4 lines, partial cut
    plain = escpos.receipt_bytes(img, cut_paper=False, drawer_pin=None)
    assert b"\x1bp" not in plain and b"\x1dV" not in plain


# --- rendering ---------------------------------------------------------------------


@pytest.fixture(autouse=True, params=["raqm", "fallback"])
def shaping(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Every test runs with Pillow's RAQM layout and with the fallback the Windows
    registers use (their Pillow wheel has no FriBiDi): both paths on every platform."""
    if request.param == "raqm" and not render.RAQM:
        pytest.skip("Pillow without RAQM on this platform")
    monkeypatch.setattr(render, "RAQM", request.param == "raqm")
    return str(request.param)


def test_fallback_lays_out_like_raqm() -> None:
    """The shaped fallback gives the same receipt geometry as HarfBuzz shaping."""
    if not render.RAQM:
        pytest.skip("needs RAQM to compare against")
    with_raqm = receipt_image(PAYLOAD, 80)
    render.RAQM = False
    try:
        fallback = receipt_image(PAYLOAD, 80)
    finally:
        render.RAQM = True
    assert fallback.size == with_raqm.size
    a = ImageChops.invert(with_raqm.convert("L")).getbbox()
    b = ImageChops.invert(fallback.convert("L")).getbbox()
    assert a and b and all(abs(x - y) <= 4 for x, y in zip(a, b, strict=True))


@pytest.mark.parametrize("width,dots", [(80, 576), (58, 384)])
def test_receipt_image_width_and_rtl(width: int, dots: int) -> None:
    img = receipt_image(PAYLOAD, width)
    assert img.width == dots and 300 < img.height < 2000
    ink = ImageChops.invert(img.convert("L")).getbbox()
    assert ink is not None
    # Right-to-left: labels start at the right margin, amounts sit at the left margin.
    assert ink[2] >= dots - 12 and ink[0] <= 12


def test_fallback_keeps_digit_only_lines_right_to_left() -> None:
    # A date-and-time line has no Persian letter to set the direction: still RTL, so the
    # date (first in the text) stays on the right as with RAQM.
    assert render._visual("۱۴۰۵/۰۷/۲۳  ۱۰:۱۵") == "۱۰:۱۵  ۱۴۰۵/۰۷/۲۳"
    assert render._visual("جمع") != "جمع"  # shaped into presentation forms


def test_long_names_wrap_instead_of_overflowing() -> None:
    long = dict(PAYLOAD, lines=[{"name": "کالای " * 30, "detail": "", "amount": "۱٬۰۰۰"}])
    short = receipt_image(PAYLOAD, 58)
    tall = receipt_image(long, 58)
    assert tall.width == 384 and tall.height > short.height


TABLE_PAYLOAD = dict(
    PAYLOAD,
    table={
        "columns": ["شرح کالا", "مقدار", "قیمت کالا", "قیمت فروشگاه", "مبلغ کل"],
        "rows": [
            ["تخم مرغ", "۱٫۴۴۲", "۳٬۴۰۰٬۰۰۰", "۲٬۵۸۰٬۰۰۰", "۳٬۷۲۰٬۳۶۰"],
            ["آب گازدار انگور شیشه‌ای ۳۳۰ م هوفنبرگ", "۲", "۶۸۵٬۰۰۰", "۵۶۳٬۰۰۰", "۱٬۱۲۶٬۰۰۰"],
        ],
    },
    contact=["۰۹۳۰۵۲۴۶۵۰۲", "ایذه، خیابان طالقانی"],
)


@pytest.mark.parametrize("raqm", [True, False])
def test_table_receipt_on_80mm_line_layout_on_58mm(raqm: bool) -> None:
    """The shop's layout (bordered item table) needs 80 mm; 58 mm keeps the line layout.
    Both shaping paths draw it."""
    if raqm and not render.RAQM:
        pytest.skip("needs RAQM")
    saved = render.RAQM
    render.RAQM = raqm
    try:
        wide = receipt_image(TABLE_PAYLOAD, 80)
        narrow = receipt_image(TABLE_PAYLOAD, 58)
        old = receipt_image(PAYLOAD, 58)
    finally:
        render.RAQM = saved
    assert wide.width == 576 and 500 < wide.height < 2000
    # The table's frame runs from margin to margin.
    ink = ImageChops.invert(wide.convert("L")).getbbox()
    assert ink is not None and ink[0] <= render.MARGIN and ink[2] >= 576 - render.MARGIN - 1
    # 58 mm: the old layout plus the contact lines, no table.
    assert narrow.width == 384 and narrow.height > old.height


# --- transport -----------------------------------------------------------------------


def test_tcp_transport_delivers_exact_bytes() -> None:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    got = bytearray()

    def accept() -> None:
        conn, _ = srv.accept()
        with conn:
            while chunk := conn.recv(65536):
                got.extend(chunk)

    srv.settimeout(10)  # never block the run if sending fails before connecting
    t = threading.Thread(target=accept, daemon=True)
    t.start()
    data = escpos.receipt_bytes(receipt_image(PAYLOAD, 80), cut_paper=True, drawer_pin=2)
    transports.TcpTransport(f"127.0.0.1:{port}").send(data)
    t.join(5)
    srv.close()
    assert bytes(got) == data
    with pytest.raises(transports.PrinterError, match="پاسخ نمی‌دهد"):
        transports.TcpTransport(f"127.0.0.1:{port}", timeout=1).send(b"x")


# --- runner ----------------------------------------------------------------------------


class FakeClient:
    def __init__(self, jobs: list[dict[str, Any] | None]) -> None:
        self.jobs, self.results, self.states = list(jobs), [], []

    def poll(self, state: str | None) -> dict[str, Any]:
        self.states.append(state)
        if not self.jobs:
            raise Unauthorized(401, "x", "revoked")
        return {"name": "R1", "printer": PRINTER, "job": self.jobs.pop(0)}

    def result(self, job_id: str, ok: bool, error: str | None = None) -> dict[str, Any]:
        self.results.append((job_id, ok, error))
        return {}


class Capture:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[bytes] = []
        self.fail = fail

    def __call__(self, transport: str, address: str | None) -> Capture:
        return self

    def send(self, data: bytes) -> None:
        if self.fail:
            raise transports.PrinterError("کاغذ تمام شده")
        self.sent.append(data)


def agent(client: FakeClient, cap: Capture) -> Agent:
    cfg = AgentConfig("http://srv", "d1", "R1", poll_interval=0.01)
    return Agent(cfg, client, cap)  # type: ignore[arg-type]


def test_runner_prints_once_reports_and_stops_when_revoked() -> None:
    job = {"id": "j1", "kind": "receipt", "payload": PAYLOAD}
    drawer = {"id": "j2", "kind": "drawer", "payload": {"pin": 5}}
    client, cap = FakeClient([job, dict(job), None, drawer]), Capture()
    a = agent(client, cap)
    a.run(threading.Event())  # ends on Unauthorized after the queue is empty
    assert client.results == [("j1", True, None), ("j2", True, None)]
    assert len(cap.sent) == 2  # the duplicate delivery of j1 was not printed again
    assert cap.sent[0].startswith(b"\x1b@\x1bp\x00")  # cash sale: drawer pin 2 with the receipt
    assert cap.sent[1] == b"\x1b@\x1bp\x01\x19\xfa"
    assert a.status.paired is False and "جفت‌سازی" in (a.status.last_error or "")
    assert a.snapshot()["recent_jobs"][0]["id"] == "j2"


def test_runner_reports_printer_failure_without_retrying() -> None:
    client, cap = (
        FakeClient([{"id": "j1", "kind": "test", "payload": PAYLOAD}, None]),
        Capture(fail=True),
    )
    a = agent(client, cap)
    assert a.step() is True
    assert client.results == [("j1", False, "کاغذ تمام شده")]
    a.step()
    assert client.states[-1] == "کاغذ تمام شده"  # reported to the server with the next poll


def test_drawer_disabled_never_pulses() -> None:
    printer = dict(PRINTER, drawer_enabled=False)
    data = Agent.build({"id": "x", "kind": "receipt", "payload": PAYLOAD}, printer)
    assert b"\x1bp" not in data


# --- local status API -------------------------------------------------------------------


def test_status_api_is_read_only_and_refuses_web_pages() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    srv = make_server(port, lambda: {"device": "R1"})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:

        def req(method: str, headers: dict[str, str]) -> int:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            c.request(method, "/status", headers=headers)
            status = c.getresponse().status
            c.close()
            return status

        assert req("GET", {"Host": f"127.0.0.1:{port}"}) == 200
        assert req("GET", {"Host": f"evil.example:{port}"}) == 403  # DNS rebinding
        assert req("GET", {"Host": f"localhost:{port}", "Origin": "http://shop.lan"}) == 403
        assert req("POST", {"Host": f"127.0.0.1:{port}"}) == 405
    finally:
        srv.shutdown()
