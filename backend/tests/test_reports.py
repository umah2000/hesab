"""Reports: one business story checked across sales, inventory, party, treasury and
financial statements; Excel export; saved filters; permissions."""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from flask import Flask
from openpyxl import load_workbook

from app.modules.inventory.services.stock import tehran_today
from tests.conftest import Api, new_key
from tests.test_inventory import D1, make_item, stock_doc
from tests.test_sales import Pos, _inv, login, open_shift, pos, sell  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def rows_by(table: dict, key: str) -> dict[str, dict]:
    return {r[key]: r for r in table["rows"]}


@pytest.fixture
def story(app: Flask, pos: Pos) -> dict:  # noqa: F811
    """Two cash sales and a card sale, one return, a credit sale, a customer receipt and a
    short cash count — the same day."""
    boss = login(app, "boss")
    c = login(app, "cashier")
    sh = open_shift(c, pos.r1)
    milk_sale = sell(
        c, pos.r1, [{"item_id": pos.milk, "qty": "2"}], [{"method": "cash", "amount": "220000"}]
    ).get_json()
    sell(
        c,
        pos.r1,
        [{"item_id": pos.bread, "qty": "1"}],
        [{"method": "card", "amount": "50000", "card_reference": "123456"}],
    )
    closed = c.post(
        f"/api/v1/sales/shifts/{sh['id']}/close",
        {"counted_cash": "210000"},
        headers={"If-Match": sh["row_version"]},
    )
    assert closed.get_json()["difference"] == "-10000.0000"

    sup = login(app, "super")
    open_shift(sup, pos.r2)
    ret = sup.post(
        f"/api/v1/sales/invoices/{milk_sale['id']}/returns",
        {
            "cash_register_id": pos.r2,
            "lines": [{"original_line_id": milk_sale["lines"][0]["id"], "qty": "1"}],
            "refunds": [{"method": "cash", "amount": "110000"}],
            "reason": "برگشت",
        },
        idem=new_key(),
    )
    assert ret.status_code == 201, ret.get_json()
    party = boss.post(
        "/api/v1/parties",
        {"code": "C9", "name": "رستوران نمونه", "credit_limit": "5000000"},
        idem=new_key(),
    ).get_json()
    credit = sell(
        sup,
        pos.r2,
        [{"item_id": pos.milk, "qty": "1"}],
        [{"method": "credit", "amount": "110000"}],
        customer_id=party["id"],
    )
    assert credit.status_code == 201, credit.get_json()
    cash = boss.post(
        "/api/v1/treasury/accounts",
        {
            "code": "CASH-9",
            "name": "صندوق اداری",
            "kind": "cash",
            "branch_id": pos_branch(app, pos),
        },
        idem=new_key(),
    ).get_json()
    rec = boss.post(
        "/api/v1/treasury/receipts",
        {
            "branch_id": pos_branch(app, pos),
            "document_date": tehran_today().isoformat(),
            "party_id": party["id"],
            "lines": [{"method": "cash", "money_account_id": cash["id"], "amount": "50000"}],
        },
        idem=new_key(),
    )
    assert rec.status_code == 201, rec.get_json()
    return {"boss": boss, "party": party}


def pos_branch(app: Flask, pos: Pos) -> str:  # noqa: F811
    from sqlalchemy import text

    from app.core.db import new_session

    with app.app_context():
        s = new_session()
        try:
            return str(
                s.scalar(text("SELECT branch_id FROM cash_register WHERE id = :id"), {"id": pos.r1})
            )
        finally:
            s.close()


def test_sales_dashboard_and_shortages(app: Flask, pos: Pos, story: dict) -> None:  # noqa: F811
    boss: Api = story["boss"]
    by_item = boss.get("/api/v1/reports/sales?group_by=item").get_json()
    rows = {r["key"].split(" — ")[0]: r for r in by_item["rows"]}
    milk, bread = rows["M1"], rows["B1"]
    # 2 sold − 1 returned + 1 on credit; this fixture prices include VAT (110 000 = 100 000 + 10%).
    assert (milk["invoices"], milk["returns"], milk["qty"]) == (2, 1, "2.000")
    assert (milk["net_sales"], milk["tax"], milk["cost"], milk["profit"], milk["margin"]) == (
        "200000.0000",
        "20000.0000",
        "160000.0000",
        "40000.0000",
        "20.00",
    )
    assert (bread["net_sales"], bread["tax"], bread["margin"]) == ("50000.0000", "0.0000", "40.00")
    assert by_item["totals"]["net_sales"] == "250000.0000"
    assert by_item["totals"]["profit"] == "60000.0000"
    assert by_item["rows"][0]["key"].startswith("M1")  # sorted by net sales
    by_day = boss.get("/api/v1/reports/sales?group_by=day").get_json()
    assert [r["key"] for r in by_day["rows"]] == [tehran_today().isoformat()]
    cashiers = boss.get("/api/v1/reports/sales?group_by=cashier").get_json()
    assert len(cashiers["rows"]) == 2
    # «همه» (ADR-0028): whole history, past the one-year limit of a chosen range.
    everything = boss.get("/api/v1/reports/sales?group_by=item&all_time=true").get_json()
    assert everything["totals"]["net_sales"] == "250000.0000"
    too_long = boss.get("/api/v1/reports/sales?date_from=2024-01-01&date_to=2026-01-01")
    assert too_long.get_json()["error"]["code"] == "range_too_long"
    one_day = boss.get(
        f"/api/v1/reports/sales?group_by=item&date_from={tehran_today()}&date_to={tehran_today()}"
    ).get_json()
    assert one_day["totals"]["net_sales"] == "250000.0000"

    dash = boss.get("/api/v1/reports/dashboard").get_json()
    cur = dash["current"]
    assert (cur["invoices"], cur["returns"], cur["net_sales"], cur["gross_profit"]) == (
        3,
        1,
        "250000.0000",
        "60000.0000",
    )
    assert dash["payments"] == {
        "card": "50000.0000",
        "cash": "110000.0000",
        "credit": "110000.0000",
    }
    assert dash["previous"]["invoices"] == 0
    assert [t["code"] for t in dash["top_items"]] == ["M1", "B1"]
    assert dash["cash_shortage"] == "10000.0000"
    assert dash["receivables"] == "60000.0000"
    assert dash["inventory_value"] is not None and len(dash["series"]) == 1

    short = boss.get("/api/v1/reports/cash-shortages").get_json()
    assert short["totals"]["shortage"] == "10000.0000"
    assert short["rows"][0]["shifts"] == 1


def test_inventory_reports(app: Flask, pos: Pos, story: dict) -> None:  # noqa: F811
    boss: Api = story["boss"]
    today = tehran_today()
    mv = boss.get(f"/api/v1/reports/stock-movement?date_from={D1.isoformat()}").get_json()
    milk = rows_by(mv, "code")["M1"]
    assert (milk["opening_qty"], milk["in_qty"], milk["out_qty"], milk["closing_qty"]) == (
        "0.000",
        "101.000",
        "3.000",
        "98.000",
    )
    later = boss.get(
        f"/api/v1/reports/stock-movement?date_from={(today - timedelta(days=2)).isoformat()}"
    ).get_json()
    assert rows_by(later, "code")["M1"]["opening_qty"] == "100.000"

    slow = boss.get("/api/v1/reports/slow-moving?days=30&cover_days=3650").get_json()
    status = {r["code"]: r["status"] for r in slow["rows"]}
    assert status == {"CH": "راکد", "W1": "راکد"}  # sold items cover less than 10 years
    slow90 = boss.get("/api/v1/reports/slow-moving?days=30&cover_days=90").get_json()
    assert {r["code"]: r["status"] for r in slow90["rows"]}["M1"] == "کم‌گردش"

    # Expiry: stock is not kept per lot, so the newest receipts are taken as what remains.
    egg = make_item(boss, _inv(pos.wh, pos_pcs(boss)), "E1", track_expiry=True)
    stock_doc(
        boss,
        "opening",
        pos.wh,
        [
            {
                "item_id": egg["id"],
                "qty": "10",
                "unit_cost": "5000",
                "expiry_date": (today + timedelta(days=5)).isoformat(),
            }
        ],
        when=D1,
    )
    stock_doc(
        boss,
        "adjustment",
        pos.wh,
        [
            {
                "item_id": egg["id"],
                "qty": "5",
                "unit_cost": "5000",
                "expiry_date": (today + timedelta(days=200)).isoformat(),
            }
        ],
        when=today,
    )
    exp = boss.get("/api/v1/reports/near-expiry?days=30").get_json()
    assert [(r["code"], r["qty"], r["days_left"]) for r in exp["rows"]] == [("E1", "10.000", 5)]


def pos_pcs(api: Api) -> str:
    return next(
        u["id"] for u in api.get("/api/v1/inventory/units").get_json() if u["code"] == "PCS"
    )


def test_parties_treasury_and_statements(app: Flask, pos: Pos, story: dict) -> None:  # noqa: F811
    boss: Api = story["boss"]
    debtors = boss.get("/api/v1/reports/debtors").get_json()
    row = rows_by(debtors, "code")["C9"]
    assert (row["balance"], row["b0"], row["b91"]) == ("60000.0000", "60000.0000", "0.0000")
    assert boss.get("/api/v1/reports/creditors").get_json()["rows"] == []

    flow = boss.get("/api/v1/reports/money-flow").get_json()
    assert rows_by(flow, "code")["CASH-9"]["in"] == "50000.0000"

    pl = boss.get("/api/v1/reports/profit-loss").get_json()
    lines = {r["name"]: r["amount"] for r in pl["rows"]}
    # Revenue 250 000 − COGS 190 000 = 60 000 gross; − shortage 10 000 = 50 000 net.
    assert lines["درآمدها"] == "250000.0000"
    assert lines["سود ناخالص"] == "60000.0000"
    assert lines["کسری صندوق"] == "10000.0000"
    assert lines["سود (زیان) خالص"] == "50000.0000"

    bs = boss.get("/api/v1/reports/balance-sheet").get_json()
    named = {r["name"]: r["amount"] for r in bs["rows"]}
    assert named["سود (زیان) دوره جاری"] == "50000.0000"
    assert named["جمع دارایی‌ها"] == named["جمع بدهی‌ها و حقوق مالکانه"]
    assert len(bs["notes"]) == 1  # no imbalance warning


def test_excel_export_saved_filters_and_permissions(app: Flask, pos: Pos, story: dict) -> None:  # noqa: F811
    boss: Api = story["boss"]
    r = boss.get("/api/v1/reports/sales?group_by=item&format=xlsx")
    assert r.status_code == 200 and r.mimetype.endswith("sheet")
    ws = load_workbook(io.BytesIO(r.data)).active
    assert ws is not None and ws.sheet_view.rightToLeft
    header = [c.value for c in ws[4]]
    assert "فروش خالص (تومان)" in header
    first = [c.value for c in ws[5]]
    assert first[0].startswith("M1") and float(first[header.index("فروش خالص (تومان)")]) == 20000

    created = boss.post(
        "/api/v1/reports/saved-filters",
        {
            "report": "sales",
            "name": "فروش کالاها",
            "params": {"group_by": "item", "page": 3, "date_from": ""},
        },
    )
    assert created.status_code == 201, created.get_json()
    assert created.get_json()["params"] == {"group_by": "item"}  # only the report's filters
    assert (
        boss.post(
            "/api/v1/reports/saved-filters",
            {"report": "sales", "name": "فروش کالاها", "params": {}},
        ).get_json()["error"]["code"]
        == "filter_name_taken"
    )
    bad = boss.post(
        "/api/v1/reports/saved-filters",
        {"report": "sales", "name": "بد", "params": {"group_by": "x"}},
    )
    assert bad.status_code == 400
    assert (
        boss.post(
            "/api/v1/reports/saved-filters", {"report": "nope", "name": "xx", "params": {}}
        ).status_code
        == 404
    )
    mine = boss.get("/api/v1/reports/saved-filters?report=sales").get_json()
    assert [f["name"] for f in mine] == ["فروش کالاها"]

    from tests.conftest import make_user

    make_user(app, "auditor", ["AUD"])
    aud = login(app, "auditor")
    keys = {r["key"] for r in aud.get("/api/v1/reports").get_json()}
    assert "money-flow" not in keys and {"sales", "profit-loss", "debtors"} <= keys
    assert aud.get("/api/v1/reports/money-flow").status_code == 403
    assert aud.get("/api/v1/reports/dashboard").status_code == 200
    assert aud.send("DELETE", f"/api/v1/reports/saved-filters/{mine[0]['id']}").status_code == 404
    cashier = login(app, "cashier")
    assert cashier.get("/api/v1/reports").status_code == 403
    assert cashier.get("/api/v1/reports/sales").status_code == 403
    assert boss.send("DELETE", f"/api/v1/reports/saved-filters/{mine[0]['id']}").status_code == 204
