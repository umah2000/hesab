"""Device Agents: pairing and tokens, job queue, receipt payload, drawer, expiry."""

from __future__ import annotations

from decimal import Decimal

import pytest
from flask import Flask
from flask.testing import FlaskClient
from nextcam_core.receipt import money
from sqlalchemy import text

from app.core.db import new_session, unit_of_work
from tests.conftest import Api, new_key
from tests.test_sales import Pos, login, open_shift, pos, sell  # noqa: F401 - fixture

pytestmark = pytest.mark.db

PRINTER = {
    "name": "صندوق ۱ — Agent",
    "printer_transport": "tcp",
    "printer_address": "192.168.1.50:9100",
    "paper_width": 80,
    "drawer_enabled": True,
    "drawer_pin": 2,
}


class Agent:
    """What the Device Agent does over HTTP: bearer token, no cookie, no CSRF."""

    def __init__(self, client: FlaskClient, token: str | None = None) -> None:
        self.c, self.token = client, token

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def pair(self, code: str):
        r = self.c.post(
            "/api/v1/devices/agent/pair",
            json={"code": code, "agent_version": "0.6.0", "platform": "Windows 10"},
        )
        if r.status_code == 201:
            self.token = r.get_json()["token"]
        return r

    def poll(self, state: str | None = "ok"):
        return self.c.post(
            "/api/v1/devices/agent/poll",
            json={"agent_version": "0.6.0", "printer_state": state},
            headers=self._h(),
        )

    def result(self, job_id: str, status: str = "done", error: str | None = None):
        return self.c.post(
            f"/api/v1/devices/agent/jobs/{job_id}/result",
            json={"status": status, "error": error},
            headers=self._h(),
        )


def make_device(boss: Api, register: str, **kw: object) -> dict:
    r = boss.post(
        "/api/v1/devices",
        {**PRINTER, "branch_id": kw.pop("branch"), "cash_register_id": register, **kw},
        idem=new_key(),
    )
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def branch_of(app: Flask, register: str) -> str:
    with app.app_context():
        s = new_session()
        try:
            return str(
                s.scalar(
                    text("SELECT branch_id FROM cash_register WHERE id = :id"), {"id": register}
                )
            )
        finally:
            s.close()


def test_receipt_money_format() -> None:
    assert money(Decimal("1100000"), "IRT") == "۱۱۰٬۰۰۰"
    assert money(Decimal("10323"), "IRT") == "۱٬۰۳۲٫۳"
    assert money(Decimal("-50000"), "IRR") == "−۵۰٬۰۰۰"
    assert money(Decimal("0"), "IRT") == "۰"


def test_pairing_tokens_and_revocation(app: Flask, pos: Pos) -> None:  # noqa: F811
    boss = login(app, "boss")
    branch = branch_of(app, pos.r1)
    dev = make_device(boss, pos.r1, branch=branch)
    assert dev["status"] == "pending" and len(dev["pairing_code"]) == 9
    again = boss.post(
        "/api/v1/devices",
        {**PRINTER, "branch_id": branch, "cash_register_id": pos.r1},
        idem=new_key(),
    )
    assert again.get_json()["error"]["code"] == "register_has_device"
    bad = boss.post(
        "/api/v1/devices",
        {**PRINTER, "branch_id": branch, "printer_address": "http://x;rm -rf"},
        idem=new_key(),
    )
    assert bad.status_code == 400
    # The code is never shown again.
    assert boss.get(f"/api/v1/devices/{dev['id']}").get_json()["pairing_code"] is None

    agent = Agent(app.test_client())
    assert agent.poll().status_code == 401
    assert agent.pair("ZZZZ-ZZZZ").status_code == 401
    assert agent.pair(dev["pairing_code"].lower().replace("-", "")).status_code == 201
    assert Agent(app.test_client()).pair(dev["pairing_code"]).status_code == 401  # one-time
    p = agent.poll()
    assert p.status_code == 200, p.get_json()
    assert p.get_json()["job"] is None
    assert p.get_json()["printer"]["address"] == "192.168.1.50:9100"
    seen = boss.get(f"/api/v1/devices/{dev['id']}").get_json()
    assert (seen["status"], seen["online"], seen["agent_version"], seen["printer_state"]) == (
        "active",
        True,
        "0.6.0",
        "ok",
    )
    # A session cookie is not a device token.
    assert boss.send("POST", "/api/v1/devices/agent/poll", {}).status_code == 401

    # Re-pairing: the old agent works until the new one pairs, then stops.
    fresh = boss.post(
        f"/api/v1/devices/{dev['id']}/pairing-code", headers={"If-Match": seen["row_version"]}
    ).get_json()
    assert agent.poll().status_code == 200
    replacement = Agent(app.test_client())
    assert replacement.pair(fresh["pairing_code"]).status_code == 201
    assert agent.poll().status_code == 401
    assert replacement.poll().status_code == 200

    cur = boss.get(f"/api/v1/devices/{dev['id']}").get_json()
    rv = boss.post(f"/api/v1/devices/{dev['id']}/revoke", headers={"If-Match": cur["row_version"]})
    assert rv.get_json()["status"] == "revoked"
    assert replacement.poll().status_code == 401
    # The register is free for a new device.
    make_device(boss, pos.r1, branch=branch)

    cashier = login(app, "cashier")
    assert cashier.get("/api/v1/devices").status_code == 403


def test_print_receipt_drawer_and_job_lifecycle(app: Flask, pos: Pos) -> None:  # noqa: F811
    boss = login(app, "boss")
    dev = make_device(boss, pos.r1, branch=branch_of(app, pos.r1))
    agent = Agent(app.test_client())
    agent.pair(dev["pairing_code"])
    agent.poll()

    c = login(app, "cashier")
    open_shift(c, pos.r1)
    assert c.get(f"/api/v1/devices/registers/{pos.r1}").get_json() == {
        "device_id": dev["id"],
        "online": True,
        "printer": True,
        "drawer": True,
    }
    sale = sell(
        c, pos.r1, [{"item_id": pos.milk, "qty": "2"}], [{"method": "cash", "amount": "220000"}]
    ).get_json()
    r = c.post("/api/v1/devices/print-receipt", {"invoice_id": sale["id"]})
    assert r.status_code == 201, r.get_json()
    job = r.get_json()
    assert job["status"] == "queued"

    got = agent.poll().get_json()["job"]
    assert got["id"] == job["id"] and got["kind"] == "receipt"
    pl = got["payload"]
    assert pl["heading"] == "فاکتور فروش" and pl["open_drawer"] is True and pl["cut"] is True
    assert pl["lines"][0]["amount"] == "۲۲٬۰۰۰"
    assert pl["lines"][0]["detail"].startswith("۲ ")
    assert ["شماره", "۱"] in pl["meta"]
    assert pl["totals"][-1]["value"] == "۲۲٬۰۰۰" or any(
        t["bold"] and t["value"] == "۲۲٬۰۰۰ تومان" for t in pl["totals"]
    )
    assert agent.poll().get_json()["job"] is None  # sent once, not again
    assert c.get(f"/api/v1/devices/jobs/{job['id']}").get_json()["status"] == "sent"
    assert agent.result(job["id"]).get_json()["status"] == "done"
    assert agent.result(job["id"]).get_json()["error"]["code"] == "job_closed"

    # A reprint never opens the drawer and is audited.
    again = c.post("/api/v1/devices/print-receipt", {"invoice_id": sale["id"]}).get_json()
    pl2 = agent.poll().get_json()["job"]["payload"]
    assert pl2["heading"] == "فاکتور فروش (چاپ مجدد)" and pl2["open_drawer"] is False
    failed = agent.result(again["id"], "failed", "کاغذ تمام شده").get_json()
    assert (failed["status"], failed["error"]) == ("failed", "کاغذ تمام شده")

    # Automatic printing off: a cash sale still opens the drawer, once, without paper.
    quiet = sell(
        c, pos.r1, [{"item_id": pos.milk, "qty": "1"}], [{"method": "cash", "amount": "110000"}]
    ).get_json()
    pulse = c.post("/api/v1/devices/print-receipt", {"invoice_id": quiet["id"], "paper": False})
    assert pulse.status_code == 201, pulse.get_json()
    pj = agent.poll().get_json()["job"]
    assert (pj["kind"], pj["payload"]) == ("drawer", {"pin": 2})
    agent.result(pj["id"])
    again_pulse = c.post(
        "/api/v1/devices/print-receipt", {"invoice_id": quiet["id"], "paper": False}
    )
    assert again_pulse.get_json()["error"]["code"] == "no_drawer"
    late = c.post("/api/v1/devices/print-receipt", {"invoice_id": quiet["id"]}).get_json()
    late_pl = agent.poll().get_json()["job"]["payload"]
    assert late_pl["open_drawer"] is False and late_pl["heading"] == "فاکتور فروش"
    agent.result(late["id"])

    card = sell(
        c,
        pos.r1,
        [{"item_id": pos.bread, "qty": "1"}],
        [{"method": "card", "amount": "50000", "card_reference": "123456"}],
    ).get_json()
    c.post("/api/v1/devices/print-receipt", {"invoice_id": card["id"]})
    assert agent.poll().get_json()["job"]["payload"]["open_drawer"] is False

    # Manual drawer opening: supervisor only, with a reason.
    body = {"cash_register_id": pos.r1, "reason": "پول خرد"}
    assert c.post("/api/v1/devices/open-drawer", body).status_code == 403
    sup = login(app, "super")
    d = sup.post("/api/v1/devices/open-drawer", body)
    assert d.status_code == 201, d.get_json()
    drawer = agent.poll().get_json()["job"]
    assert (drawer["kind"], drawer["payload"]) == ("drawer", {"pin": 2})

    with app.app_context():
        s = new_session()
        try:
            actions = dict(
                s.execute(
                    text(
                        "SELECT action, COUNT(*) FROM audit_event WHERE action IN "
                        "('devices.receipt_reprinted','devices.drawer_opened','devices.paired') "
                        "GROUP BY action"
                    )
                ).all()
            )
        finally:
            s.close()
    assert actions == {
        "devices.receipt_reprinted": 1,
        "devices.drawer_opened": 1,
        "devices.paired": 1,
    }

    # Stale work is never printed late; an offline agent sends the POS to browser printing.
    queued = c.post("/api/v1/devices/print-receipt", {"invoice_id": card["id"]}).get_json()
    with app.app_context(), unit_of_work() as s:
        s.execute(
            text(
                "UPDATE device_job SET created_at = DATEADD(minute, -5, created_at) WHERE id = :id"
            ),
            {"id": queued["id"]},
        )
    assert agent.poll().get_json()["job"] is None
    assert c.get(f"/api/v1/devices/jobs/{queued['id']}").get_json()["status"] == "expired"
    with app.app_context(), unit_of_work() as s:
        s.execute(
            text(
                "UPDATE device SET last_seen_at = DATEADD(minute, -5, last_seen_at) WHERE id = :id"
            ),
            {"id": dev["id"]},
        )
    off = c.post("/api/v1/devices/print-receipt", {"invoice_id": sale["id"]})
    assert off.get_json()["error"]["code"] == "device_offline"
    assert c.get(f"/api/v1/devices/registers/{pos.r1}").get_json()["online"] is False

    # Another register's agent cannot answer for this one's jobs.
    other = make_device(boss, pos.r2, branch=branch_of(app, pos.r2))
    stranger = Agent(app.test_client())
    stranger.pair(other["pairing_code"])
    assert stranger.result(queued["id"]).status_code == 404

    test = boss.post(f"/api/v1/devices/{other['id']}/test-print")
    assert test.status_code == 201
    page = stranger.poll().get_json()["job"]
    assert page["kind"] == "test" and page["payload"]["heading"] == "صفحه آزمایشی چاپگر"
    hist = boss.get(f"/api/v1/devices/{dev['id']}/jobs").get_json()
    assert sorted(j["status"] for j in hist) == [
        "done",
        "done",
        "done",
        "expired",
        "failed",
        "sent",
        "sent",
    ]
    expired = next(j for j in hist if j["status"] == "expired")
    assert expired["error"] == "دستگاه در زمان مقرر در دسترس نبود"
