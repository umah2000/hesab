"""Protocol-level tests. They prove the bytes and the behaviour, not a printer model."""

from __future__ import annotations

import http.client
import socket
import threading
from typing import Any

import pytest
from PIL import Image, ImageChops

from nextcam_agent import escpos, transports
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


@pytest.mark.parametrize("width,dots", [(80, 576), (58, 384)])
def test_receipt_image_width_and_rtl(width: int, dots: int) -> None:
    img = receipt_image(PAYLOAD, width)
    assert img.width == dots and 300 < img.height < 2000
    ink = ImageChops.invert(img.convert("L")).getbbox()
    assert ink is not None
    # Right-to-left: labels start at the right margin, amounts sit at the left margin.
    assert ink[2] >= dots - 12 and ink[0] <= 12


def test_long_names_wrap_instead_of_overflowing() -> None:
    long = dict(PAYLOAD, lines=[{"name": "کالای " * 30, "detail": "", "amount": "۱٬۰۰۰"}])
    short = receipt_image(PAYLOAD, 58)
    tall = receipt_image(long, 58)
    assert tall.width == 384 and tall.height > short.height


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

    t = threading.Thread(target=accept)
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
