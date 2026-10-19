"""Field sales: app sign-in with rotating tokens, assigned customers, orders priced on the
server, approval with credit, invoicing into the books, visits and the report (ADR-0018)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import select

from app.core.db import unit_of_work
from app.modules.accounting.models import DetailAccount
from tests.conftest import PASSWORD, Api, make_user
from tests.test_inventory import balance
from tests.test_sales import Pos, login, pos, voucher  # noqa: F401 - fixture

pytestmark = pytest.mark.db


class Phone:
    """What the Android app does: bearer tokens, no cookies, no CSRF."""

    def __init__(self, client: FlaskClient) -> None:
        self.c = client
        self.access: str | None = None
        self.refresh_token: str | None = None

    def login(self, username: str, password: str = PASSWORD):  # type: ignore[no-untyped-def]
        r = self.c.post(
            "/api/v1/auth/mobile/login",
            json={"username": username, "password": password, "device_name": "Galaxy A14"},
        )
        if r.status_code == 200:
            self.access, self.refresh_token = r.json["access_token"], r.json["refresh_token"]
        return r

    def refresh(self, token: str | None = None):  # type: ignore[no-untyped-def]
        r = self.c.post(
            "/api/v1/auth/mobile/refresh", json={"refresh_token": token or self.refresh_token}
        )
        if r.status_code == 200:
            self.access, self.refresh_token = r.json["access_token"], r.json["refresh_token"]
        return r

    def h(self, **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access}", **extra}

    def get(self, path: str, **extra: str):  # type: ignore[no-untyped-def]
        return self.c.get("/api/v1" + path, headers=self.h(**extra))

    def post(self, path: str, body: Any = None):  # type: ignore[no-untyped-def]
        return self.c.post("/api/v1" + path, json=body, headers=self.h())


def order(customer: str, lines: list[dict[str, str]], **kw: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "customer_id": customer,
        "lines": lines,
        "ordered_at": datetime.now(UTC).isoformat(),
        **kw,
    }


@pytest.fixture
def field(app: Flask, pos: Pos) -> dict[str, Any]:  # noqa: F811
    branch = None
    with app.app_context(), unit_of_work() as s:
        c1 = s.scalar(select(DetailAccount).where(DetailAccount.code == "C1"))
        assert c1 is not None
        c2 = DetailAccount(code="C2", name="بقالی محله", kind="person", is_active=True)
        s.add(c2)
        s.flush()
        from app.modules.organization.models import CashRegister

        reg = s.get(CashRegister, uuid.UUID(pos.r1))
        assert reg is not None
        branch = reg.branch_id
        ids = {"c1": str(c1.id), "c2": str(c2.id), "branch": str(branch)}
    user = make_user(app, "visitor1", ["VIS"], [branch])
    boss = login(app, "boss")
    v = boss.post(
        "/api/v1/distribution/visitors",
        {"user_id": str(user), "branch_id": ids["branch"], "code": "v01"},
    )
    assert v.status_code == 201, v.get_json()
    a = boss.send(
        "PUT",
        f"/api/v1/distribution/visitors/{v.json['id']}/customers",
        {"customers": [{"customer_id": ids["c1"], "visit_weekday": 0}]},
    )
    assert a.status_code == 200, a.get_json()
    return {**ids, "visitor": v.json, "boss": boss}


def test_mobile_tokens_rotate_and_stay_on_the_app_api(app: Flask, field: dict[str, Any]) -> None:
    phone = Phone(app.test_client())
    assert phone.login("visitor1", "wrong").status_code == 401
    assert phone.login("boss").status_code == 403  # no visitor permission
    r = phone.login("visitor1")
    assert r.status_code == 200, r.get_json()
    assert r.json["access_token"].startswith("ncm_a_") and r.json["user"]["username"] == "visitor1"
    assert phone.get("/distribution/mobile/bootstrap").status_code == 200
    # The bearer token opens the app's API only, never the back office.
    assert phone.get("/auth/me").json["error"]["code"] == "mobile_only"
    assert phone.get("/distribution/orders").json["error"]["code"] == "mobile_only"
    # A device token or a garbage bearer is no user.
    bad = app.test_client().get(
        "/api/v1/distribution/mobile/bootstrap", headers={"Authorization": "Bearer ncm_a_x"}
    )
    assert bad.status_code == 401

    first = phone.refresh_token
    assert phone.refresh().status_code == 200
    assert phone.get("/distribution/mobile/bootstrap").status_code == 200
    # The old refresh token again: someone copied it — the whole session ends.
    stolen = phone.refresh(first)
    assert stolen.status_code == 401
    assert phone.get("/distribution/mobile/bootstrap").status_code == 401
    assert phone.refresh().status_code == 401

    again = Phone(app.test_client())
    again.login("visitor1")
    assert again.post("/auth/mobile/logout").status_code == 200
    assert again.get("/distribution/mobile/bootstrap").status_code == 401


def test_orders_are_priced_by_the_server_and_flow_into_the_books(
    app: Flask,
    pos: Pos,  # noqa: F811
    field: dict[str, Any],
) -> None:
    phone = Phone(app.test_client())
    phone.login("visitor1")
    boot = phone.get("/distribution/mobile/bootstrap")
    assert boot.status_code == 200
    data = boot.json
    assert [c["code"] for c in data["customers"]] == ["C1"]
    assert data["customers"][0]["visit_weekday"] == 0
    assert data["customers"][0]["available"] == "1000000.0000"
    water = next(i for i in data["items"] if i["id"] == pos.water)
    assert [(u["factor"], u["price"]) for u in water["units"]] == [
        ("1", "15000.0000"),
        ("6", "90000.0000"),
    ]
    assert (
        phone.get(
            "/distribution/mobile/bootstrap", **{"If-None-Match": boot.headers["ETag"]}
        ).status_code
        == 304
    )

    lines = [
        {"item_id": pos.milk, "qty": "2"},
        {"item_id": pos.water, "qty": "1", "unit_id": pos.pack},
    ]
    q = phone.post("/distribution/mobile/quote", {"customer_id": field["c1"], "lines": lines})
    assert q.status_code == 200, q.get_json()
    assert (q.json["grand_total"], q.json["available_after"]) == ("310000.0000", "690000.0000")

    # Not this visitor's customer.
    other = phone.post("/distribution/mobile/orders", order(field["c2"], lines))
    assert other.json["error"]["code"] == "not_assigned"

    body = order(field["c1"], lines, client_total="300000", note="تحویل صبح")
    r = phone.post("/distribution/mobile/orders", body)
    assert r.status_code == 201, r.get_json()
    o = r.json
    assert (o["number"], o["status"], o["grand_total"], o["price_changed"]) == (
        1,
        "submitted",
        "310000.0000",
        True,
    )
    resent = phone.post("/distribution/mobile/orders", body)
    assert resent.status_code == 200 and resent.json["number"] == 1
    assert balance(app, pos.milk, pos.wh)[0] == "100.000"  # an order moves no stock

    visit = {
        "id": str(uuid.uuid4()),
        "customer_id": field["c1"],
        "visited_at": datetime.now(UTC).isoformat(),
        "outcome": "order",
        "order_id": o["id"],
    }
    assert phone.post("/distribution/mobile/visits", visit).status_code == 201
    assert phone.post("/distribution/mobile/visits", visit).status_code == 200

    boss: Api = field["boss"]
    inbox = boss.get("/api/v1/distribution/orders?status=open").get_json()
    assert inbox["total"] == 1 and inbox["items"][0]["price_changed"] is True
    rv = o["row_version"]
    ok = boss.post(f"/api/v1/distribution/orders/{o['id']}/approve", {}, headers={"If-Match": rv})
    assert ok.status_code == 200, ok.get_json()
    assert ok.json["status"] == "approved" and ok.json["decided_by_name"]

    # A second order over the remaining credit (approved orders count against it).
    big = phone.post(
        "/distribution/mobile/orders", order(field["c1"], [{"item_id": pos.milk, "qty": "7"}])
    ).json
    refused = boss.post(
        f"/api/v1/distribution/orders/{big['id']}/approve",
        {},
        headers={"If-Match": big["row_version"]},
    )
    assert refused.json["error"]["code"] == "credit_limit_exceeded"
    assert (
        phone.post(f"/distribution/mobile/orders/{big['id']}/cancel").json["status"] == "cancelled"
    )
    assert phone.post(f"/distribution/mobile/orders/{o['id']}/cancel").status_code == 409

    inv = boss.post(
        f"/api/v1/distribution/orders/{o['id']}/invoice",
        {"cash_register_id": pos.r1},
        headers={"If-Match": ok.json["row_version"]},
    )
    assert inv.status_code == 200, inv.get_json()
    assert inv.json["status"] == "invoiced" and inv.json["invoice_number"] == 1
    sale = boss.get(f"/api/v1/sales/invoices/{inv.json['invoice_id']}").get_json()
    assert (sale["grand_total"], sale["customer_name"], sale["payments"][0]["method"]) == (
        "310000.0000",
        "رستوران آفتاب",
        "credit",
    )
    # Milk 2 × 80 000 + water 6 × 10 000 at cost; VAT-inclusive prices in this fixture.
    books = voucher(app, sale["voucher_id"])
    assert books["6101"] == ("220000", "0") and books["1301"] == ("0", "220000")
    assert sum(Decimal(d) for d, _ in books.values()) == sum(Decimal(c) for _, c in books.values())
    assert balance(app, pos.milk, pos.wh)[0] == "98.000"
    assert balance(app, pos.water, pos.wh)[0] == "54.000"

    # What the customer now owes counts against the next order.
    q2 = phone.post("/distribution/mobile/quote", {"customer_id": field["c1"], "lines": lines})
    assert q2.json["balance"] == "310000.0000"

    done = boss.post(
        f"/api/v1/distribution/orders/{o['id']}/deliver",
        {"note": "تحویل به انباردار رستوران"},
        headers={"If-Match": inv.json["row_version"]},
    )
    assert done.json["status"] == "delivered" and done.json["delivered_at"]
    mine = phone.get("/distribution/mobile/orders").json
    assert {(m["number"], m["status"]) for m in mine} == {(1, "delivered"), (2, "cancelled")}

    rep = boss.get("/api/v1/reports/visitor-performance").get_json()
    row = rep["rows"][0]
    assert (row["visits"], row["productive"], row["hit_rate"], row["orders"], row["sold"]) == (
        1,
        1,
        "100.00",
        1,
        "310000.0000",
    )
    visits = boss.get("/api/v1/distribution/visits").get_json()
    assert visits[0]["outcome"] == "order" and visits[0]["order_id"] == o["id"]


def test_back_office_rules(app: Flask, field: dict[str, Any]) -> None:
    boss: Api = field["boss"]
    cashier_id = make_user(app, "plain_cashier", ["CSH"])
    no_role = boss.post(
        "/api/v1/distribution/visitors",
        {"user_id": str(cashier_id), "branch_id": field["branch"], "code": "v02"},
    )
    assert no_role.json["error"]["code"] == "not_a_visitor"
    v = field["visitor"]
    dup = boss.post(
        "/api/v1/distribution/visitors",
        {"user_id": v["user_id"], "branch_id": field["branch"], "code": "v03"},
    )
    assert dup.status_code == 409
    # A stopped visitor's app gets nothing.
    off = boss.send(
        "PUT",
        f"/api/v1/distribution/visitors/{v['id']}",
        {"branch_id": field["branch"], "is_active": False},
        {"If-Match": v["row_version"]},
    )
    assert off.status_code == 200 and off.json["is_active"] is False
    phone = Phone(app.test_client())
    phone.login("visitor1")
    assert phone.get("/distribution/mobile/bootstrap").json["error"]["code"] == "no_visitor"
    # The visitor role alone opens nothing in the back office.
    web = login(app, "visitor1")
    assert web.get("/api/v1/distribution/orders").status_code == 403
    assert login(app, "cashier").get("/api/v1/distribution/visitors").status_code == 403
