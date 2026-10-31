"""Stock lots by expiry date (ADR-0027): receipts make lots, issues take the earliest expiry
first, a line naming an expiry takes that lot, a transfer carries the dates, a return goes
back to the lot it was sold from; the near-expiry report and the dashboard read the lots;
an item can be created with its opening stock."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import select

from app.core.db import unit_of_work
from app.modules.inventory.models import StockLot, Warehouse
from app.modules.inventory.services.stock import tehran_today
from tests.conftest import Api, Seed, make_user, new_key
from tests.test_inventory import stock_doc
from tests.test_sales import Pos, login, open_shift, pos, sell  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def lots(api: Api, item: str) -> list[tuple[str, str | None, str]]:
    r = api.get(f"/api/v1/inventory/items/{item}/lots")
    assert r.status_code == 200, r.get_json()
    return [(x["warehouse_name"], x["expiry_date"], x["qty"]) for x in r.get_json()]


def test_lots_follow_receipts_sales_returns_waste_and_transfers(
    app: Flask,
    seed: Seed,
    pos: Pos,  # noqa: F811
) -> None:
    boss = login(app, "boss")
    today = tehran_today()
    soon, near, far = (today + timedelta(days=d) for d in (20, 5, 90))
    with app.app_context(), unit_of_work() as s:
        main = s.get(Warehouse, uuid.UUID(pos.wh))
        assert main is not None
        side = Warehouse(branch_id=seed.branch_a, code="W2", name="انبار دوم", is_active=True)
        s.add(side)
        s.flush()
        wh2, main_name = str(side.id), main.name
    item = {
        "code": "Y1",
        "name": "ماست",
        "base_unit_id": boss.get("/api/v1/inventory/items/" + pos.milk).get_json()["base_unit_id"],
        "track_expiry": True,
    }
    item["prices"] = [{"unit_id": item["base_unit_id"], "price": "10000"}]

    # Created with its opening stock; without the expiry date neither is saved.
    no_date = boss.post(
        "/api/v1/inventory/items",
        {**item, "opening": {"warehouse_id": pos.wh, "qty": "10", "unit_cost": "50000"}},
        idem=new_key(),
    )
    assert no_date.status_code in (400, 422), no_date.get_json()
    r = boss.post(
        "/api/v1/inventory/items",
        {
            **item,
            "opening": {
                "warehouse_id": pos.wh,
                "qty": "10",
                "unit_cost": "50000",
                "expiry_date": soon.isoformat(),
            },
        },
        idem=new_key(),
    )
    assert r.status_code == 201, r.get_json()
    y = r.get_json()
    assert lots(boss, y["id"]) == [(main_name, soon.isoformat(), "10.000")]
    # Opening stock only on creation.
    upd = boss.put(
        f"/api/v1/inventory/items/{y['id']}",
        {**item, "opening": {"warehouse_id": pos.wh, "qty": "1", "unit_cost": "1"}},
        y["row_version"],
    )
    assert upd.status_code in (400, 422), upd.get_json()

    for qty, expiry in (("5", near), ("4", far)):
        stock_doc(
            boss,
            "adjustment",
            pos.wh,
            [
                {
                    "item_id": y["id"],
                    "qty": qty,
                    "unit_cost": "50000",
                    "expiry_date": expiry.isoformat(),
                }
            ],
            when=today,
        )
    assert [e for _, e, _ in lots(boss, y["id"])] == [x.isoformat() for x in (near, soon, far)]

    # A sale of 7 takes the 5 expiring first, then 2 of the next.
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    sale = sell(
        c,
        pos.r1,
        [{"item_id": y["id"], "qty": "7"}],
        [{"method": "cash", "amount": "70000"}],
    )
    assert sale.status_code == 201, sale.get_json()
    assert lots(boss, y["id"]) == [
        (main_name, soon.isoformat(), "8.000"),
        (main_name, far.isoformat(), "4.000"),
    ]

    # A returned item goes back to the latest lot the sale took from.
    sup = login(app, "super")
    open_shift(sup, pos.r2)
    ret = sup.post(
        f"/api/v1/sales/invoices/{sale.get_json()['id']}/returns",
        {
            "cash_register_id": pos.r2,
            "lines": [{"original_line_id": sale.get_json()["lines"][0]["id"], "qty": "1"}],
            "refunds": [{"method": "cash", "amount": "10000"}],
            "reason": "خراب",
        },
        idem=new_key(),
    )
    assert ret.status_code == 201, ret.get_json()
    assert lots(boss, y["id"])[0] == (main_name, soon.isoformat(), "9.000")

    # Waste of the far batch names its expiry date; a transfer keeps the dates.
    stock_doc(
        boss,
        "adjustment",
        pos.wh,
        [{"item_id": y["id"], "qty": "-2", "expiry_date": far.isoformat()}],
        when=today,
    )
    stock_doc(boss, "transfer", pos.wh, [{"item_id": y["id"], "qty": "3"}], when=today, dest=wh2)
    assert sorted(lots(boss, y["id"])) == sorted(
        [
            (main_name, soon.isoformat(), "6.000"),
            (main_name, far.isoformat(), "2.000"),
            ("انبار دوم", soon.isoformat(), "3.000"),
        ]
    )
    with app.app_context(), unit_of_work() as s:
        # Lots always add up to the stock.
        total = sum(
            (
                lot.qty
                for lot in s.scalars(select(StockLot).where(StockLot.item_id == uuid.UUID(y["id"])))
            ),
            Decimal(0),
        )
        assert total == Decimal(11)

    # The report lists the lots expiring within 30 days, exactly.
    rep = boss.get("/api/v1/reports/near-expiry?days=30").get_json()
    mine = [(r["warehouse"], r["expiry"], r["qty"]) for r in rep["rows"] if r["code"] == "Y1"]
    assert sorted(mine) == sorted(
        [(main_name, soon.isoformat(), "6.000"), ("انبار دوم", soon.isoformat(), "3.000")]
    )

    # Dashboard: two lots within 30 days, none urgent; a longer warning sees the third.
    dash = boss.get("/api/v1/reports/dashboard").get_json()["expiry"]
    assert (dash["expired"], dash["urgent"], dash["soon"], dash["warn_days"]) == (0, 0, 2, 30)
    admin = login(app, "admin")
    org = admin.get("/api/v1/organization/settings").get_json()
    bad = admin.put(
        "/api/v1/organization/settings",
        {"expiry_warn_days": 10, "expiry_urgent_days": 20},
        org["row_version"],
    )
    assert bad.status_code == 400
    ok = admin.put(
        "/api/v1/organization/settings",
        {"expiry_warn_days": 100, "expiry_urgent_days": 25, "economic_code": "411111111111"},
        org["row_version"],
    )
    assert ok.status_code == 200, ok.get_json()
    assert ok.get_json()["economic_code"] == "411111111111"
    dash = boss.get("/api/v1/reports/dashboard").get_json()["expiry"]
    assert (dash["urgent"], dash["soon"]) == (2, 1)


def test_opening_stock_needs_the_stock_permission(
    app: Flask,
    seed: Seed,
    pos: Pos,  # noqa: F811
) -> None:
    make_user(app, "buyer", ["PUR"], [seed.branch_a])
    buyer = login(app, "buyer")
    unit = buyer.get("/api/v1/inventory/items/" + pos.milk).get_json()["base_unit_id"]
    body = {"code": "Z1", "name": "کالا زد", "base_unit_id": unit}
    r = buyer.post(
        "/api/v1/inventory/items",
        {**body, "opening": {"warehouse_id": pos.wh, "qty": "1", "unit_cost": "1"}},
        idem=new_key(),
    )
    assert r.status_code == 403
    assert buyer.post("/api/v1/inventory/items", body, idem=new_key()).status_code == 201
