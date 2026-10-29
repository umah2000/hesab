"""Visitor app v2 (ADR-0026): every invoice of a customer labelled by channel (view only),
the visitor's own report and monthly target, collections approved by the treasury into
ordinary receipts, new-customer requests, customer location and notifications."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import jdatetime
import pytest
from flask import Flask
from sqlalchemy import select

from app.core.db import new_session
from app.modules.distribution.models import Visit
from app.modules.inventory.services.stock import tehran_today
from app.modules.parties.models import Party
from app.modules.treasury.models import Cheque
from tests.conftest import Api, make_user, new_key
from tests.test_distribution import Phone, field, order  # noqa: F401 - fixture
from tests.test_sales import Pos, login, open_shift, pos, sell  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def _approve_and_invoice(boss: Api, pos: Pos, o: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    ok = boss.post(
        f"/api/v1/distribution/orders/{o['id']}/approve", {}, headers={"If-Match": o["row_version"]}
    )
    assert ok.status_code == 200, ok.get_json()
    inv = boss.post(
        f"/api/v1/distribution/orders/{o['id']}/invoice",
        {"cash_register_id": pos.r1},
        headers={"If-Match": ok.json["row_version"]},
    )
    assert inv.status_code == 200, inv.get_json()
    return inv.json


def _visit(phone: Phone, customer: str, outcome: str, **kw: Any) -> None:
    r = phone.post(
        "/distribution/mobile/visits",
        {
            "id": str(uuid.uuid4()),
            "customer_id": customer,
            "visited_at": datetime.now(UTC).isoformat(),
            "outcome": outcome,
            **kw,
        },
    )
    assert r.status_code == 201, r.get_json()


def test_history_report_target_and_notifications(
    app: Flask,
    pos: Pos,  # noqa: F811
    field: dict[str, Any],  # noqa: F811
) -> None:
    boss: Api = field["boss"]
    phone = Phone(app.test_client())
    phone.login("visitor1")
    milk = [{"item_id": pos.milk, "qty": "2"}]

    # 1. This visitor's order, invoiced.
    mine = phone.post("/distribution/mobile/orders", order(field["c1"], milk)).json
    mine_inv = _approve_and_invoice(boss, pos, mine)
    _visit(phone, field["c1"], "order", order_id=mine["id"], latitude="36.290100",
           longitude="59.607000", accuracy_m=12)  # fmt: skip
    _visit(phone, field["c1"], "stocked")
    # 2. Another visitor of the same customer.
    user2 = make_user(app, "visitor2", ["VIS"], [uuid.UUID(field["branch"])])
    v2 = boss.post(
        "/api/v1/distribution/visitors",
        {"user_id": str(user2), "branch_id": field["branch"], "code": "v02"},
    ).json
    boss.send(
        "PUT",
        f"/api/v1/distribution/visitors/{v2['id']}/customers",
        {"customers": [{"customer_id": field["c1"]}]},
    )
    other = Phone(app.test_client())
    other.login("visitor2")
    theirs = other.post(
        "/distribution/mobile/orders", order(field["c1"], [{"item_id": pos.water, "qty": "3"}])
    ).json
    _approve_and_invoice(boss, pos, theirs)
    # 3. Bought in the shop on credit.
    sup = login(app, "super")
    open_shift(sup, pos.r2)
    shop = sell(
        sup, pos.r2, milk, [{"method": "credit", "amount": "220000"}], customer_id=field["c1"]
    )
    assert shop.status_code == 201, shop.get_json()

    h = phone.get(f"/distribution/mobile/customers/{field['c1']}/history")
    assert h.status_code == 200, h.get_json()
    channels = {(i["channel"], i["visitor_name"]) for i in h.json["invoices"]}
    assert channels == {("mine", None), ("visitor", "کاربر visitor2"), ("shop", None)}
    assert h.json["frequent_items"][0]["item_id"] == pos.milk
    assert h.json["frequent_items"][0]["times"] == 2
    shop_id = shop.get_json()["id"]
    detail = phone.get(f"/distribution/mobile/invoices/{shop_id}")
    assert detail.status_code == 200 and detail.json["channel"] == "shop"
    assert [(ln["item_id"], ln["qty"]) for ln in detail.json["lines"]] == [(pos.milk, "2.000")]
    # Never a customer of somebody else; read only (no write route exists).
    assert phone.get(f"/distribution/mobile/customers/{field['c2']}/history").status_code == 403
    assert phone.post(f"/distribution/mobile/invoices/{shop_id}").status_code == 405

    # Only this visitor's own work is in the report.
    r = phone.get("/distribution/mobile/report?period=month")
    assert r.status_code == 200, r.get_json()
    cur = r.json["current"]
    assert (cur["ordered_count"], cur["ordered_amount"]) == (1, mine["grand_total"])
    assert (cur["invoiced_count"], cur["invoiced_amount"]) == (1, mine_inv["grand_total"])
    assert cur["customers"] == 1 and cur["visits"] == 2
    assert cur["no_order_reasons"] == {"stocked": 1}
    assert [c["name"] for c in r.json["top_customers"]] == ["رستوران آفتاب"]
    assert r.json["top_items"][0]["id"] == pos.milk and r.json["target"] is None
    day = phone.get(f"/distribution/mobile/report?period=day&date={tehran_today()}").json
    assert day["current"]["ordered_count"] == 1 and day["previous"]["ordered_count"] == 0
    week = phone.get("/distribution/mobile/report?period=week").json
    assert (week["end"] > week["start"]) and week["current"]["ordered_count"] == 1

    # Target of this Jalali month; progress is the invoiced amount.
    j = jdatetime.date.fromgregorian(date=tehran_today())
    t = boss.send(
        "PUT",
        f"/api/v1/distribution/visitors/{field['visitor']['id']}/targets/{j.year}/{j.month}",
        {"amount": "1000000"},
    )
    assert t.status_code == 200, t.get_json()
    assert t.json["invoiced"] == mine_inv["grand_total"]
    path = f"/api/v1/distribution/visitors/{field['visitor']['id']}/targets/{j.year}/{j.month}"
    # Changing an existing target needs the version the manager saw.
    assert boss.send("PUT", path, {"amount": "900000"}).json["error"]["code"] == "version_conflict"
    t = boss.send("PUT", path, {"amount": "1000000"}, headers={"If-Match": t.json["row_version"]})
    assert t.status_code == 200, t.get_json()
    listed = boss.get(f"/api/v1/distribution/targets?year={j.year}&month={j.month}").get_json()
    assert {x["visitor_name"]: x["amount"] for x in listed} == {
        "کاربر visitor1": "1000000.0000",
        "کاربر visitor2": None,
    }
    r = phone.get("/distribution/mobile/report?period=month").json
    assert (r["target"], r["target_progress"]) == ("1000000.0000", mine_inv["grand_total"])

    # Visit positions are kept.
    with app.app_context():
        s = new_session()
        try:
            located = s.scalar(select(Visit).where(Visit.order_id == uuid.UUID(mine["id"])))
            assert located is not None and located.latitude == Decimal("36.290100")
        finally:
            s.close()

    notes = phone.get("/distribution/mobile/notifications").json
    kinds = [n["kind"] for n in notes]
    assert {"order_approved", "order_invoiced", "target_set"} <= set(kinds)
    assert all(n["read_at"] is None for n in notes)
    assert phone.post("/distribution/mobile/notifications/read", {"all": True}).json["updated"] == 4
    assert all(n["read_at"] for n in phone.get("/distribution/mobile/notifications").json)
    # Each visitor sees only their own.
    assert {n["kind"] for n in other.get("/distribution/mobile/notifications").json} == {
        "order_approved",
        "order_invoiced",
    }


def test_collections_become_receipts_only_when_the_treasury_approves(
    app: Flask,
    pos: Pos,  # noqa: F811
    field: dict[str, Any],  # noqa: F811
) -> None:
    boss: Api = field["boss"]
    phone = Phone(app.test_client())
    phone.login("visitor1")
    o = phone.post(
        "/distribution/mobile/orders", order(field["c1"], [{"item_id": pos.milk, "qty": "3"}])
    ).json
    inv = _approve_and_invoice(boss, pos, o)
    acc = phone.get(f"/distribution/mobile/customers/{field['c1']}/account").json
    assert acc["balance"] == inv["grand_total"] and acc["statement"]

    cash = {
        "id": str(uuid.uuid4()),
        "customer_id": field["c1"],
        "method": "cash",
        "amount": "100000",
        "collected_at": datetime.now(UTC).isoformat(),
        "note": "بابت فاکتور",
    }
    first = phone.post("/distribution/mobile/collections", cash)
    assert first.status_code == 201, first.get_json()
    assert phone.post("/distribution/mobile/collections", cash).status_code == 200
    acc = phone.get(f"/distribution/mobile/customers/{field['c1']}/account").json
    # Not yet money in the books: the balance is unchanged until the treasury approves.
    assert (acc["balance"], acc["pending_collections"]) == (inv["grand_total"], "100000.0000")
    bad = dict(cash, id=str(uuid.uuid4()), method="cheque")
    assert phone.post("/distribution/mobile/collections", bad).status_code == 400
    other = dict(cash, id=str(uuid.uuid4()), customer_id=field["c2"])
    assert phone.post("/distribution/mobile/collections", other).status_code == 404

    box = boss.post(
        "/api/v1/treasury/accounts",
        {"code": "CASH-V", "name": "صندوق ویزیتورها", "kind": "cash", "branch_id": field["branch"]},
        idem=new_key(),
    )
    assert box.status_code == 201, box.get_json()
    c = first.json
    need = boss.post(
        f"/api/v1/distribution/collections/{c['id']}/approve",
        {},
        headers={"If-Match": c["row_version"]},
    )
    assert need.json["error"]["code"] == "money_account_required"
    ok = boss.post(
        f"/api/v1/distribution/collections/{c['id']}/approve",
        {"money_account_id": box.json["id"]},
        headers={"If-Match": c["row_version"]},
    )
    assert ok.status_code == 200, ok.get_json()
    assert ok.json["status"] == "approved" and ok.json["treasury_document_number"]
    doc = boss.get(f"/api/v1/treasury/documents/{ok.json['treasury_document_id']}").get_json()
    assert (doc["kind"], doc["status"], doc["amount"]) == ("receipt", "final", "100000.0000")
    acc = phone.get(f"/distribution/mobile/customers/{field['c1']}/account").json
    expected = Decimal(inv["grand_total"]) - Decimal(100000)
    assert Decimal(acc["balance"]) == expected and acc["pending_collections"] == "0.0000"
    again = boss.post(
        f"/api/v1/distribution/collections/{c['id']}/approve",
        {"money_account_id": box.json["id"]},
        headers={"If-Match": ok.json["row_version"]},
    )
    assert again.json["error"]["code"] == "not_pending"

    cheque = dict(
        cash,
        id=str(uuid.uuid4()),
        method="cheque",
        amount="150000",
        cheque_number="452100",
        cheque_bank="ملت",
        cheque_due_date="2026-12-10",
    )
    ch = phone.post("/distribution/mobile/collections", cheque).json
    ok2 = boss.post(
        f"/api/v1/distribution/collections/{ch['id']}/approve",
        {},
        headers={"If-Match": ch["row_version"]},
    )
    assert ok2.status_code == 200, ok2.get_json()
    acc = phone.get(f"/distribution/mobile/customers/{field['c1']}/account").json
    assert [(x["number"], x["status"]) for x in acc["open_cheques"]] == [("452100", "in_hand")]
    with app.app_context():
        s = new_session()
        try:
            assert s.scalar(select(Cheque.amount).where(Cheque.number == "452100")) == Decimal(
                "150000.0000"
            )
        finally:
            s.close()

    transfer = dict(cash, id=str(uuid.uuid4()), method="transfer", reference="TRK-9981")
    tr = phone.post("/distribution/mobile/collections", transfer).json
    no = boss.post(
        f"/api/v1/distribution/collections/{tr['id']}/reject",
        {"note": "واریز پیدا نشد"},
        headers={"If-Match": tr["row_version"]},
    )
    assert no.json["status"] == "rejected"
    listed = boss.get("/api/v1/distribution/collections?status=pending").get_json()
    assert listed["total"] == 0
    mine = phone.get("/distribution/mobile/collections").json
    assert {m["status"] for m in mine} == {"approved", "rejected"}
    kinds = {n["kind"] for n in phone.get("/distribution/mobile/notifications").json}
    assert {"collection_approved", "collection_rejected"} <= kinds
    # The app's bearer token never opens the back office.
    assert phone.get("/distribution/collections").json["error"]["code"] == "mobile_only"


def test_new_customer_requests_and_customer_location(
    app: Flask,
    pos: Pos,  # noqa: F811
    field: dict[str, Any],  # noqa: F811
) -> None:
    boss: Api = field["boss"]
    phone = Phone(app.test_client())
    phone.login("visitor1")
    req = {
        "id": str(uuid.uuid4()),
        "name": "سوپر ستاره",
        "owner_name": "حسن رضایی",
        "mobile": "09123456789",
        "address": "خیابان امام، پلاک ۴۰",
        "visit_weekday": 2,
        "latitude": "36.300000",
        "longitude": "59.600000",
    }
    r = phone.post("/distribution/mobile/customer-requests", req)
    assert r.status_code == 201, r.get_json()
    assert phone.post("/distribution/mobile/customer-requests", req).status_code == 200
    pending = boss.get("/api/v1/distribution/customer-requests?status=pending").get_json()
    assert [p["name"] for p in pending["items"]] == ["سوپر ستاره"]
    ok = boss.post(
        f"/api/v1/distribution/customer-requests/{r.json['id']}/approve",
        {"code": "C77", "credit_limit": "5000000"},
        headers={"If-Match": r.json["row_version"]},
    )
    assert ok.status_code == 200, ok.get_json()
    assert (ok.json["status"], ok.json["party_code"]) == ("approved", "C77")
    boot = phone.get("/distribution/mobile/bootstrap").json
    new = next(c for c in boot["customers"] if c["code"] == "C77")
    assert (new["visit_weekday"], new["latitude"], new["credit_limit"]) == (
        2,
        "36.3",
        "5000000.0000",
    )

    second = dict(req, id=str(uuid.uuid4()), name="سوپر نیما")
    r2 = phone.post("/distribution/mobile/customer-requests", second).json
    no = boss.post(
        f"/api/v1/distribution/customer-requests/{r2['id']}/reject",
        {"note": "تکراری است"},
        headers={"If-Match": r2["row_version"]},
    )
    assert no.json["status"] == "rejected"
    mine = phone.get("/distribution/mobile/customer-requests").json
    assert {(m["name"], m["status"]) for m in mine} == {
        ("سوپر ستاره", "approved"),
        ("سوپر نیما", "rejected"),
    }

    loc = {"latitude": "36.288000", "longitude": "59.615500"}
    put = phone.c.put(
        f"/api/v1/distribution/mobile/customers/{field['c1']}/location", json=loc, headers=phone.h()
    )
    assert put.status_code == 204
    other = phone.c.put(
        f"/api/v1/distribution/mobile/customers/{field['c2']}/location", json=loc, headers=phone.h()
    )
    assert other.status_code == 404
    bad = phone.c.put(
        f"/api/v1/distribution/mobile/customers/{field['c1']}/location",
        json={"latitude": "95", "longitude": "0"},
        headers=phone.h(),
    )
    assert bad.status_code == 400
    with app.app_context():
        s = new_session()
        try:
            p = s.get(Party, uuid.UUID(field["c1"]))
            assert p is not None and (p.latitude, p.longitude) == (
                Decimal("36.288000"),
                Decimal("59.615500"),
            )
        finally:
            s.close()
