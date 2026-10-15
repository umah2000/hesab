"""Offline sales: snapshot, push, idempotency, conflicts and their resolution (ADR-0017)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import select

from app.core.db import new_session
from app.modules.inventory.services.stock import tehran_today
from app.modules.sales.models import SalesInvoice
from tests.conftest import Api
from tests.test_devices import Agent, branch_of, make_device
from tests.test_inventory import balance
from tests.test_sales import Pos, login, open_shift, pos, voucher  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def rial(d: Decimal) -> Decimal:
    return d.quantize(Decimal(1), rounding="ROUND_HALF_UP")


def line(item: str, unit: str, qty: str, price: str, *, rate: str = "10", exempt: bool = False):
    """A line priced the way the register does it (VAT-inclusive, as in the pos fixture)."""
    gross = rial(Decimal(qty) * Decimal(price))
    r = Decimal(0) if exempt else Decimal(rate)
    tax = rial(gross * r / (100 + r))
    return {
        "item_id": item,
        "unit_id": unit,
        "qty": qty,
        "unit_price": price,
        "price_source": "list",
        "gross": str(gross),
        "promotion_discount": "0",
        "manual_discount": "0",
        "vat_exempt": exempt,
        "vat_rate": str(r),
        "tax": str(tax),
        "line_total": str(gross),
    }


class Register:
    def __init__(self, app: Flask, pos: Pos) -> None:  # noqa: F811
        self.app, self.pos = app, pos
        self.boss = login(app, "boss")
        dev = make_device(self.boss, pos.r1, branch=branch_of(app, pos.r1))
        self.device_id = dev["id"]
        self.agent = Agent(app.test_client())
        assert self.agent.pair(dev["pairing_code"]).status_code == 201
        self.seq = 0

    def h(self, **kw: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.agent.token}", **kw}

    def snapshot(self, etag: str | None = None):
        extra = {"If-None-Match": etag} if etag else {}
        return self.agent.c.get("/api/v1/sync/agent/snapshot", headers=self.h(**extra))

    def sale(self, snap: dict, lines: list[dict], **kw: Any) -> dict:
        self.seq += 1
        op_id = str(uuid.uuid4())
        total = sum((Decimal(ln["line_total"]) for ln in lines), Decimal(0))
        sale = {
            "id": op_id,
            "device_number": f"{snap['number_prefix']}-{self.seq}",
            "sold_at": datetime.now(UTC).isoformat(),
            "cash_register_id": self.pos.r1,
            "shift_id": snap["shift"]["id"],
            "user_id": snap["shift"]["user_id"],
            "snapshot_version": snap["version"],
            "prices_include_vat": True,
            "lines": lines,
            "subtotal": str(sum((Decimal(ln["gross"]) for ln in lines), Decimal(0))),
            "discount_total": str(
                sum(
                    (
                        Decimal(ln["promotion_discount"]) + Decimal(ln["manual_discount"])
                        for ln in lines
                    ),
                    Decimal(0),
                )
            ),
            "tax_total": str(sum((Decimal(ln["tax"]) for ln in lines), Decimal(0))),
            "grand_total": str(total),
            "payments": [{"method": "cash", "amount": str(total)}],
        }
        sale.update(kw)
        return {"id": op_id, "type": "sale", "local_time": sale["sold_at"], "sale": sale}

    def push(self, *ops: dict) -> list[dict]:
        r = self.agent.c.post("/api/v1/sync/agent/push", json={"ops": list(ops)}, headers=self.h())
        assert r.status_code == 200, r.get_json()
        return r.get_json()["results"]

    def poll(self, queue: int):
        return self.agent.c.post(
            "/api/v1/devices/agent/poll", json={"offline_queue": queue}, headers=self.h()
        )


def unit_ids(app: Flask) -> dict[str, str]:
    from app.modules.inventory.models import Unit

    with app.app_context():
        s = new_session()
        try:
            return {u.code: str(u.id) for u in s.scalars(select(Unit))}
        finally:
            s.close()


def invoice(app: Flask, inv_id: str) -> SalesInvoice:
    with app.app_context():
        s = new_session()
        try:
            inv = s.get(SalesInvoice, uuid.UUID(inv_id))
            assert inv is not None
            s.expunge(inv)
            return inv
        finally:
            s.close()


def test_snapshot_and_offline_sale_is_applied_once(app: Flask, pos: Pos) -> None:  # noqa: F811
    reg = Register(app, pos)
    u = unit_ids(app)
    no_shift = reg.snapshot().get_json()
    assert no_shift["shift"] is None  # nobody can sell offline without an open shift

    cashier = login(app, "cashier")
    shift = open_shift(cashier, pos.r1, "100000")
    r = reg.snapshot()
    assert r.status_code == 200, r.get_json()
    snap = r.get_json()
    assert snap["shift"]["id"] == shift["id"] and "sales.pos.use" in snap["shift"]["permissions"]
    assert not any(p.startswith("users.") for p in snap["shift"]["permissions"])
    assert snap["cash_register"]["warehouse_id"] == pos.wh
    assert snap["settings"]["prices_include_vat"] is True
    milk = next(i for i in snap["items"] if i["id"] == pos.milk)
    assert milk["stock"] == "100.000"
    assert {"item_id": pos.milk, "unit_id": u["PCS"], "price": "110000.0000"} in snap["prices"]
    assert any(b["item_id"] == pos.milk for b in snap["barcodes"])
    assert snap["scale_rules"][0]["prefix"] == "21"
    assert len(snap["number_prefix"]) == 8
    # Unchanged content → 304, so a register can ask often.
    etag = r.headers["ETag"]
    assert reg.snapshot(etag).status_code == 304
    # A session cookie is not a device token.
    assert reg.boss.get("/api/v1/sync/agent/snapshot").status_code == 401

    # Sold offline at an older milk price (100 000 instead of 110 000).
    op = reg.sale(
        snap,
        [
            line(pos.milk, u["PCS"], "2", "100000"),
            line(pos.bread, u["PCS"], "1", "50000", exempt=True),
        ],
        cash_tendered="300000",
    )
    [res] = reg.push(op)
    assert (res["status"], res["number"]) == ("applied", 1), res
    inv = invoice(app, res["invoice_id"])
    assert inv.device_number == op["sale"]["device_number"]
    assert inv.document_date == tehran_today() and inv.status == "final"
    assert inv.grand_total == Decimal(250000) and inv.change_due == Decimal(50000)
    assert inv.shift_id is not None and str(inv.shift_id) == shift["id"]
    assert voucher(app, str(inv.voucher_id)) == {
        "1101": ("250000", "0"),
        "5101": ("0", "231818"),
        "3201": ("0", "18182"),
        "6101": ("190000", "0"),
        "1301": ("0", "190000"),
    }
    assert balance(app, pos.milk, pos.wh)[0] == "98.000"

    # Resending (the answer was lost) changes nothing.
    [again] = reg.push(op)
    assert again == res
    assert balance(app, pos.milk, pos.wh)[0] == "98.000"

    ops = reg.boss.get("/api/v1/sync/operations?status=applied").get_json()
    assert ops["total"] == 1
    row = ops["items"][0]
    assert (row["price_difference"], row["invoice_number"], row["grand_total"]) == (
        "-20000.0000",
        1,
        "250000.0000",
    )

    # The shift cannot be closed while the register still holds offline sales.
    assert reg.poll(2).status_code == 200
    dev = reg.boss.get(f"/api/v1/devices/{reg.device_id}").get_json()
    assert dev["offline_queue"] == 2 and dev["last_sync_at"] is not None
    blocked = cashier.post(
        f"/api/v1/sales/shifts/{shift['id']}/close",
        {"counted_cash": "350000"},
        headers={"If-Match": shift["row_version"]},
    )
    assert blocked.get_json()["error"]["code"] == "offline_sales_pending"
    reg.poll(0)
    closed = cashier.post(
        f"/api/v1/sales/shifts/{shift['id']}/close",
        {"counted_cash": "350000"},
        headers={"If-Match": shift["row_version"]},
    )
    assert closed.status_code == 200, closed.get_json()
    assert closed.get_json()["difference"] == "0.0000"  # the offline cash is in the count


def test_rejections_never_block_the_queue(app: Flask, pos: Pos) -> None:  # noqa: F811
    reg = Register(app, pos)
    u = unit_ids(app)
    open_shift(login(app, "cashier"), pos.r1)
    snap = reg.snapshot().get_json()

    tampered = reg.sale(snap, [line(pos.milk, u["PCS"], "1", "110000")])
    tampered["sale"]["lines"][0]["tax"] = "0"
    foreign = reg.sale(snap, [line(pos.milk, u["PCS"], "1", "110000")])
    foreign["sale"]["device_number"] = "ABCDEF12-1"
    broken = {"id": str(uuid.uuid4()), "type": "sale", "local_time": "now", "sale": {}}
    good = reg.sale(snap, [line(pos.milk, u["PCS"], "1", "110000")])
    no_id = {"type": "sale"}
    res = reg.push(tampered, foreign, broken, good, no_id)
    assert [(r["status"], r["code"]) for r in res] == [
        ("rejected", "bad_totals"),
        ("rejected", "wrong_number"),
        ("rejected", "invalid"),
        ("applied", None),
        ("rejected", "invalid"),
    ]
    assert res[3]["number"] == 1
    # Rejected operations are kept for a person to see; they cannot be applied.
    inbox = reg.boss.get("/api/v1/sync/operations?status=open").get_json()
    assert inbox["total"] == 3
    rej = next(o for o in inbox["items"] if o["code"] == "bad_totals")
    no = reg.boss.post(
        f"/api/v1/sync/operations/{rej['id']}/resolve",
        {"action": "apply", "note": "تست"},
        headers={"If-Match": rej["row_version"]},
    )
    assert no.get_json()["error"]["code"] == "not_applicable"
    ok = reg.boss.post(
        f"/api/v1/sync/operations/{rej['id']}/resolve",
        {"action": "discard", "note": "داده دست‌کاری‌شده"},
        headers={"If-Match": rej["row_version"]},
    )
    assert ok.get_json()["status"] == "discarded"
    # Only people with sync.resolve see the inbox.
    assert login(app, "cashier").get("/api/v1/sync/operations").status_code == 403


def test_conflicts_wait_for_a_manager(app: Flask, pos: Pos) -> None:  # noqa: F811
    reg = Register(app, pos)
    u = unit_ids(app)
    cashier = login(app, "cashier")
    shift = open_shift(cashier, pos.r1)
    snap = reg.snapshot().get_json()

    # 1. The shift was closed before the sale arrived.
    late = reg.sale(snap, [line(pos.milk, u["PCS"], "1", "110000")])
    # 2. The register's clock is two days ahead.
    future = reg.sale(
        snap,
        [line(pos.bread, u["PCS"], "1", "50000", exempt=True)],
        sold_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
    )
    # 3. A manual discount the cashier may not give.
    disc = line(pos.milk, u["PCS"], "1", "110000")
    disc.update(manual_discount="10000", tax="9091", line_total="100000")
    discount = reg.sale(snap, [disc])
    closed = cashier.post(
        f"/api/v1/sales/shifts/{shift['id']}/close",
        {"counted_cash": "0"},
        headers={"If-Match": shift["row_version"]},
    )
    assert closed.status_code == 200, closed.get_json()
    res = reg.push(late, future, discount)
    assert [(r["status"], r["code"]) for r in res] == [
        ("conflict", "shift_closed"),
        ("conflict", "clock"),
        ("conflict", "shift_closed"),
    ]
    assert balance(app, pos.milk, pos.wh)[0] == "100.000"  # nothing booked yet

    inbox = reg.boss.get("/api/v1/sync/operations?status=conflict").get_json()["items"]
    first = next(o for o in inbox if o["id"] == late["id"])
    assert first["cashier_name"] and first["grand_total"] == "110000.0000"
    done = reg.boss.post(
        f"/api/v1/sync/operations/{late['id']}/resolve",
        {"action": "apply", "note": "پول در صندوق بود؛ مغایرت شیفت جداگانه اصلاح می‌شود"},
        headers={"If-Match": first["row_version"]},
    )
    assert done.status_code == 200, done.get_json()
    out = done.get_json()
    assert out["status"] == "resolved" and out["invoice_number"] == 1
    assert out["resolved_by_name"] and out["resolution_note"]
    assert balance(app, pos.milk, pos.wh)[0] == "99.000"
    twice = reg.boss.post(
        f"/api/v1/sync/operations/{late['id']}/resolve",
        {"action": "discard", "note": "دوباره"},
        headers={"If-Match": out["row_version"]},
    )
    assert twice.status_code == 409
    # Resending the operation returns the resolution, it is not applied again.
    [again] = reg.push(late)
    assert (again["status"], again["number"]) == ("resolved", 1)

    fut = next(o for o in inbox if o["id"] == future["id"])
    gone = reg.boss.post(
        f"/api/v1/sync/operations/{future['id']}/resolve",
        {"action": "discard", "note": "فروش تکراری"},
        headers={"If-Match": fut["row_version"]},
    )
    assert gone.get_json()["status"] == "discarded"
    assert balance(app, pos.milk, pos.wh)[0] == "99.000"

    # In an open shift the discount is still not the cashier's to give.
    shift2 = open_shift(cashier, pos.r1)
    snap2 = reg.snapshot().get_json()
    assert snap2["shift"]["id"] == shift2["id"]
    [d2] = reg.push(reg.sale(snap2, [disc]))
    assert (d2["status"], d2["code"]) == ("conflict", "not_permitted")


def test_locked_period_is_a_conflict(app: Flask, pos: Pos) -> None:  # noqa: F811
    reg = Register(app, pos)
    u = unit_ids(app)
    open_shift(login(app, "cashier"), pos.r1)
    snap = reg.snapshot().get_json()
    years = reg.boss.get("/api/v1/accounting/fiscal-years").get_json()
    today = tehran_today().isoformat()
    period = next(
        p for y in years for p in y["periods"] if p["start_date"] <= today <= p["end_date"]
    )

    def lock(on: bool, version: str) -> str:
        r = reg.boss.send(
            "PUT",
            f"/api/v1/accounting/fiscal-periods/{period['id']}/lock",
            {"is_locked": on},
            {"If-Match": version},
        )
        assert r.status_code == 200, r.get_json()
        fresh = reg.boss.get("/api/v1/accounting/fiscal-years").get_json()
        return next(
            p["row_version"] for y in fresh for p in y["periods"] if p["id"] == period["id"]
        )

    locked = lock(True, period["row_version"])
    op = reg.sale(snap, [line(pos.milk, u["PCS"], "1", "110000")])
    [res] = reg.push(op)
    assert (res["status"], res["code"]) == ("conflict", "period_locked")
    row = reg.boss.get(f"/api/v1/sync/operations/{op['id']}").get_json()
    still = reg.boss.post(
        f"/api/v1/sync/operations/{op['id']}/resolve",
        {"action": "apply", "note": "ثبت"},
        headers={"If-Match": row["row_version"]},
    )
    assert still.get_json()["error"]["code"] == "period_locked"
    lock(False, locked)
    ok = reg.boss.post(
        f"/api/v1/sync/operations/{op['id']}/resolve",
        {"action": "apply", "note": "ثبت پس از بازکردن دوره"},
        headers={"If-Match": row["row_version"]},
    )
    assert ok.get_json()["status"] == "resolved", ok.get_json()


def test_device_without_register_has_no_snapshot(app: Flask, pos: Pos) -> None:  # noqa: F811
    boss: Api = login(app, "boss")
    dev = make_device(boss, None, branch=branch_of(app, pos.r1))  # type: ignore[arg-type]
    agent = Agent(app.test_client())
    agent.pair(dev["pairing_code"])
    r = agent.c.get(
        "/api/v1/sync/agent/snapshot", headers={"Authorization": f"Bearer {agent.token}"}
    )
    assert r.get_json()["error"]["code"] == "no_register"
