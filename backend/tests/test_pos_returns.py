"""ADR-0029: a manual invoice number besides the automatic one; a cashier finds an invoice by
either number on the register and returns goods with a supervisor's approval; a
suggested code for a new item."""

from __future__ import annotations

import pytest
from flask import Flask

from tests.conftest import new_key
from tests.test_inventory import balance
from tests.test_sales import Pos, login, open_shift, pos, sell  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def test_manual_number_find_and_return_at_the_register(app: Flask, pos: Pos) -> None:  # noqa: F811
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    milk3 = [{"item_id": pos.milk, "qty": "3"}]
    cash = [{"method": "cash", "amount": "330000"}]
    sale = sell(c, pos.r1, milk3, cash, manual_number="STD-1405-0001")
    assert sale.status_code == 201, sale.get_json()
    inv = sale.get_json()
    assert (inv["manual_number"], inv["number"]) == ("STD-1405-0001", 1)
    again = sell(c, pos.r1, milk3, cash, manual_number="STD-1405-0001")
    assert again.get_json()["error"]["code"] == "manual_number_taken"
    assert sell(c, pos.r1, milk3, cash, manual_number="bad number!").status_code == 400

    boss = login(app, "boss")
    found = boss.get("/api/v1/sales/invoices?search=STD-1405-0001").get_json()["items"]
    assert [x["id"] for x in found] == [inv["id"]]
    assert boss.get("/api/v1/sales/invoices?search=۱").get_json()["items"][0]["id"] == inv["id"]

    # The cashier finds it on the register by either number (Persian digits too).
    base = f"/api/v1/sales/registers/{pos.r1}/invoices/find?number="
    assert c.get(base + "STD-1405-0001").get_json()["id"] == inv["id"]
    assert c.get(base + "۱").get_json()["id"] == inv["id"]
    assert c.get(base + "999").status_code == 404

    # A return by the cashier needs a supervisor's approval on the register.
    stock_before = balance(app, pos.milk, pos.wh)[0]
    body = {
        "cash_register_id": pos.r1,
        "lines": [{"original_line_id": inv["lines"][0]["id"], "qty": "1"}],
        "refunds": [{"method": "cash"}],
        "reason": "تاریخ گذشته",
    }
    url = f"/api/v1/sales/invoices/{inv['id']}/returns"
    refused = c.post(url, body, idem=new_key())
    assert refused.get_json()["error"]["code"] == "approval_required", refused.get_json()
    approval = c.post(
        "/api/v1/sales/approvals",
        {
            "cash_register_id": pos.r1,
            "action": "return",
            "username": "super",
            "password": "Test-Passw0rd",
        },
    )
    assert approval.status_code == 201, approval.get_json()
    ret = c.post(url, {**body, "approval_id": approval.get_json()["id"]}, idem=new_key())
    assert ret.status_code == 201, ret.get_json()
    assert (ret.get_json()["kind"], ret.get_json()["grand_total"]) == ("return", "110000.0000")
    # The goods are back in stock; the invoice shows what was returned.
    assert float(balance(app, pos.milk, pos.wh)[0]) == float(stock_before) + 1
    assert c.get(base + "STD-1405-0001").get_json()["lines"][0]["returned_qty"] == "1.000"
    # An approval is used once.
    reuse = c.post(url, {**body, "approval_id": approval.get_json()["id"]}, idem=new_key())
    assert reuse.get_json()["error"]["code"] == "approval_expired"


def test_next_item_code(app: Flask, pos: Pos) -> None:  # noqa: F811
    boss = login(app, "boss")
    r = boss.get("/api/v1/inventory/items/next-code")
    assert r.status_code == 200, r.get_json()
    code = r.get_json()["code"]
    assert code.isdigit()
    assert boss.get(f"/api/v1/inventory/items?q={code}").get_json()["items"] == []
    assert login(app, "cashier").get("/api/v1/inventory/items/next-code").status_code == 403
