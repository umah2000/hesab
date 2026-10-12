"""Purchasing: drafts, landed costs, finalisation (stock + voucher), immutability, returns,
orders and receipts, price history and the due list."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import new_session, unit_of_work
from app.modules.accounting.models import Account, VoucherLine
from app.modules.accounting.services.chart import seed_defaults
from app.modules.accounting.services.fiscal import ensure_year
from app.modules.inventory.models import Unit, Warehouse
from app.modules.inventory.services.catalog import seed_catalog
from app.modules.inventory.services.stock import ensure_default_warehouses, tehran_today
from tests.conftest import Api, Seed, make_user, new_key
from tests.test_inventory import balance, make_item
from tests.test_sales import _inv

pytestmark = pytest.mark.db

D = date(2026, 5, 1)


@dataclass
class Buy:
    api: Api
    wh: str
    supplier: str
    carrier: str
    milk: str
    bread: str
    water: str
    pack: str


def login(app: Flask, username: str) -> Api:
    a = Api(app.test_client())
    assert a.login(username).status_code == 200
    return a


@pytest.fixture
def buy(app: Flask, seed: Seed) -> Buy:
    with app.app_context(), unit_of_work() as s:
        seed_defaults(s)
        ensure_year(s, 1405)
        seed_catalog(s)
        ensure_default_warehouses(s)
        wh = str(s.scalar(select(Warehouse.id).where(Warehouse.branch_id == seed.branch_a)))
        units = {u.code: str(u.id) for u in s.scalars(select(Unit))}
    make_user(app, "buyer", ["PUR", "ACC"])
    api = login(app, "buyer")
    pcs = units["PCS"]

    def party(code: str, **kw: object) -> str:
        body = {"code": code, "name": f"تأمین {code}", "is_customer": False, "is_supplier": True}
        r = api.post("/api/v1/parties", {**body, **kw}, idem=new_key())
        assert r.status_code == 201, r.get_json()
        return r.get_json()["id"]

    milk = make_item(api, _inv(wh, pcs), "M1")
    bread = make_item(api, _inv(wh, pcs), "B1", vat_exempt=True)
    water = make_item(api, _inv(wh, pcs), "W1", units=[{"unit_id": units["PACK"], "factor": "6"}])
    return Buy(
        api=api,
        wh=wh,
        supplier=party("S1", payment_terms_days=30),
        carrier=party("T1"),
        milk=milk["id"],
        bread=bread["id"],
        water=water["id"],
        pack=units["PACK"],
    )


def invoice_body(b: Buy, when: date = D, **kw: object) -> dict:
    return {
        "warehouse_id": b.wh,
        "supplier_id": b.supplier,
        "document_date": when.isoformat(),
        "supplier_invoice_no": "F-1001",
        "lines": [
            {"item_id": b.milk, "qty": "100", "unit_cost": "80000", "discount": "200000"},
            {"item_id": b.water, "unit_id": b.pack, "qty": "10", "unit_cost": "54000"},
            {"item_id": b.bread, "qty": "50", "unit_cost": "30000"},
        ],
        "charges": [
            {"description": "کرایه حمل", "amount": "984000"},
            {"description": "تخلیه", "amount": "100000", "payee_id": b.carrier},
        ],
        **kw,
    }


def draft(b: Buy, **kw: object) -> dict:
    r = b.api.post("/api/v1/purchasing/invoices", invoice_body(b, **kw), idem=new_key())
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def finalize(b: Buy, inv: dict):
    return b.api.post(
        f"/api/v1/purchasing/invoices/{inv['id']}/finalize",
        headers={"If-Match": inv["row_version"]},
    )


def voucher_lines(app: Flask, voucher_id: str) -> list[tuple[str, str, str]]:
    with app.app_context():
        s = new_session()
        try:
            rows = s.execute(
                select(Account.code, VoucherLine.debit, VoucherLine.credit)
                .join(Account, Account.id == VoucherLine.account_id)
                .where(VoucherLine.voucher_id == voucher_id)
            ).all()
            return sorted(
                (c, format(d.normalize(), "f"), format(cr.normalize(), "f")) for c, d, cr in rows
            )
        finally:
            s.close()


def test_draft_landed_costs_finalize_and_voucher(app: Flask, buy: Buy) -> None:
    inv = draft(buy)
    lines = {ln["item_id"]: ln for ln in inv["lines"]}
    milk, water, bread = lines[buy.milk], lines[buy.water], lines[buy.bread]
    assert (milk["net"], milk["tax"], milk["vat_rate"]) == ("7800000.0000", "780000.0000", "10.00")
    assert (water["base_qty"], water["net"]) == ("60.000", "540000.0000")
    assert (bread["tax"], bread["vat_rate"]) == ("0.0000", "0.00")
    # Landed costs by net value; the largest line takes the rounding residue.
    assert (water["landed"], bread["landed"], milk["landed"]) == (
        "59488.0000",
        "165244.0000",
        "859268.0000",
    )
    assert (inv["cost_total"], inv["tax_total"], inv["grand_total"]) == (
        "10924000.0000",
        "834000.0000",
        "11758000.0000",
    )
    assert inv["due_date"] == (D + timedelta(days=30)).isoformat()
    assert inv["status"] == "draft" and inv["number"] is None
    assert balance(app, buy.milk, buy.wh)[0] == "0"  # a draft has no effect

    done = finalize(buy, inv)
    assert done.status_code == 200, done.get_json()
    fin = done.get_json()
    assert fin["status"] == "final" and fin["number"] == 1 and fin["stock_document_id"]
    assert balance(app, buy.milk, buy.wh) == ("100.000", "8659268.0000", "86592.68")
    assert balance(app, buy.water, buy.wh)[:2] == ("60.000", "599488.0000")
    assert voucher_lines(app, fin["voucher_id"]) == [
        ("1301", "10924000", "0"),
        ("1402", "834000", "0"),
        ("3101", "0", "100000"),
        ("3101", "0", "11658000"),
    ]
    sup = buy.api.get(f"/api/v1/parties/{buy.supplier}").get_json()
    carrier = buy.api.get(f"/api/v1/parties/{buy.carrier}").get_json()
    assert (sup["balance"], carrier["balance"]) == ("-11658000.0000", "-100000.0000")

    # Final is final: no edit, no delete, no second finalise — and the DB agrees.
    body = invoice_body(buy)
    assert (
        buy.api.put(
            f"/api/v1/purchasing/invoices/{fin['id']}", body, fin["row_version"]
        ).get_json()["error"]["code"]
        == "invoice_final"
    )
    assert finalize(buy, fin).get_json()["error"]["code"] == "invoice_final"
    with app.app_context(), pytest.raises(DBAPIError), unit_of_work() as s:
        s.execute(
            text("UPDATE purchase_invoice SET grand_total = 1 WHERE id = :id"),
            {"id": fin["id"]},
        )
    with app.app_context(), pytest.raises(DBAPIError), unit_of_work() as s:
        s.execute(
            text("UPDATE purchase_invoice_line SET net = 1 WHERE invoice_id = :id"),
            {"id": fin["id"]},
        )

    # The same supplier invoice number cannot be booked twice.
    again = draft(buy)
    assert finalize(buy, again).get_json()["error"]["code"] == "duplicate_supplier_invoice"
    gone = buy.api.send(
        "DELETE",
        f"/api/v1/purchasing/invoices/{again['id']}",
        headers={"If-Match": again["row_version"]},
    )
    assert gone.status_code == 204

    hist = buy.api.get(f"/api/v1/purchasing/items/{buy.milk}/price-history").get_json()
    assert [(h["number"], h["unit_cost"], h["base_unit_cost"]) for h in hist] == [
        (1, "80000.0000", "86593.0000")
    ]
    # A price far from the last purchase is flagged on the next draft.
    odd = invoice_body(buy, supplier_invoice_no="F-2")
    odd["lines"] = [{"item_id": buy.milk, "qty": "10", "unit_cost": "800000"}]
    odd["charges"] = []
    warned = buy.api.post("/api/v1/purchasing/invoices", odd, idem=new_key()).get_json()
    assert len(warned["warnings"]) == 1 and "۲۵٪" in warned["warnings"][0]


def test_return_at_purchase_cost(app: Flask, buy: Buy) -> None:
    fin = finalize(buy, draft(buy)).get_json()
    milk = next(ln for ln in fin["lines"] if ln["item_id"] == buy.milk)
    path = f"/api/v1/purchasing/invoices/{fin['id']}/returns"
    body = {
        "document_date": D.isoformat(),
        "reason": "تاریخ نزدیک",
        "lines": [{"original_line_id": milk["id"], "qty": "10"}],
    }
    r = buy.api.post(path, body, idem=new_key())
    assert r.status_code == 201, r.get_json()
    ret = r.get_json()
    assert (ret["kind"], ret["status"], ret["number"], ret["original_number"]) == (
        "return",
        "final",
        1,
        1,
    )
    assert (ret["grand_total"], ret["tax_total"], ret["cost_total"]) == (
        "858000.0000",
        "78000.0000",
        "865927.0000",
    )
    # Goods leave at the cost they came in with; the unrefunded landed share is an expense.
    assert balance(app, buy.milk, buy.wh)[:2] == ("90.000", "7793341.0000")
    assert voucher_lines(app, ret["voucher_id"]) == [
        ("1301", "0", "865927"),
        ("1402", "0", "78000"),
        ("3101", "858000", "0"),
        ("6101", "85927", "0"),
    ]
    seen = buy.api.get(f"/api/v1/purchasing/invoices/{fin['id']}").get_json()
    assert next(ln for ln in seen["lines"] if ln["id"] == milk["id"])["returnable_qty"] == "90.000"
    too_many = {**body, "lines": [{"original_line_id": milk["id"], "qty": "91"}]}
    assert (
        buy.api.post(path, too_many, idem=new_key()).get_json()["error"]["code"]
        == "return_qty_exceeded"
    )
    # The rest goes back exactly: nothing is left in stock, no rounding residue.
    rest = {**body, "lines": [{"original_line_id": milk["id"], "qty": "90"}]}
    assert buy.api.post(path, rest, idem=new_key()).status_code == 201
    assert balance(app, buy.milk, buy.wh)[:2] == ("0.000", "0.0000")


def test_order_receipt_and_close(app: Flask, buy: Buy) -> None:
    r = buy.api.post(
        "/api/v1/purchasing/orders",
        {
            "warehouse_id": buy.wh,
            "supplier_id": buy.supplier,
            "order_date": D.isoformat(),
            "lines": [{"item_id": buy.milk, "qty": "100", "unit_cost": "80000"}],
        },
        idem=new_key(),
    )
    assert r.status_code == 201, r.get_json()
    order = r.get_json()
    assert (order["status"], order["number"], order["estimated_total"]) == (
        "draft",
        None,
        "8000000.0000",
    )
    line = order["lines"][0]["id"]

    def receive(qty: str, no: str, **kw: object):
        body = invoice_body(buy, supplier_invoice_no=no, order_id=order["id"], **kw)
        body["lines"] = [
            {"item_id": buy.milk, "qty": qty, "unit_cost": "80000", "order_line_id": line}
        ]
        body["charges"] = []
        return buy.api.post("/api/v1/purchasing/invoices", body, idem=new_key())

    assert receive("60", "A").get_json()["error"]["code"] == "order_not_open"
    ok = buy.api.post(
        f"/api/v1/purchasing/orders/{order['id']}/approve",
        headers={"If-Match": order["row_version"]},
    )
    assert ok.status_code == 200, ok.get_json()
    order = ok.get_json()
    assert (order["status"], order["number"]) == ("approved", 1)

    first = receive("60", "A").get_json()
    assert finalize(buy, first).status_code == 200
    order = buy.api.get(f"/api/v1/purchasing/orders/{order['id']}").get_json()
    assert (order["status"], order["lines"][0]["received_base_qty"]) == ("approved", "60.000")
    cancel = buy.api.post(
        f"/api/v1/purchasing/orders/{order['id']}/cancel",
        headers={"If-Match": order["row_version"]},
    )
    assert cancel.get_json()["error"]["code"] == "order_received"

    assert finalize(buy, receive("40", "B").get_json()).status_code == 200
    order = buy.api.get(f"/api/v1/purchasing/orders/{order['id']}").get_json()
    assert (order["status"], order["lines"][0]["received_base_qty"]) == ("closed", "100.000")
    listed = buy.api.get("/api/v1/purchasing/orders?status=closed").get_json()
    assert [o["number"] for o in listed["items"]] == [1]


def test_dues_validation_and_permissions(app: Flask, buy: Buy) -> None:
    today = tehran_today()
    inv = draft(buy, when=today - timedelta(days=40))
    assert inv["due_date"] == (today - timedelta(days=10)).isoformat()
    assert finalize(buy, inv).status_code == 200
    later = draft(buy, when=today - timedelta(days=5), supplier_invoice_no="F-2")
    assert finalize(buy, later).status_code == 200
    due = buy.api.get("/api/v1/purchasing/dues?days=0").get_json()
    # Only the overdue one; the supplier owes 2 × 11 658 000 and neither is paid.
    assert [(d["number"], d["outstanding"], d["overdue_days"]) for d in due] == [
        (1, "11658000.0000", 10)
    ]
    assert len(buy.api.get("/api/v1/purchasing/dues?days=30").get_json()) == 2

    bad = invoice_body(buy)
    bad["lines"][0]["discount"] = "99000000"
    r = buy.api.post("/api/v1/purchasing/invoices", bad, idem=new_key())
    assert r.get_json()["error"]["code"] == "discount_too_high"
    bad = invoice_body(buy, supplier_id=buy.carrier)
    with app.app_context(), unit_of_work() as s:
        s.execute(
            text("UPDATE party SET is_supplier = 0, is_customer = 1 WHERE id = :id"),
            {"id": buy.carrier},
        )
    r = buy.api.post("/api/v1/purchasing/invoices", bad, idem=new_key())
    assert r.get_json()["error"]["code"] == "not_a_supplier"
    frac = invoice_body(buy)
    frac["lines"] = [{"item_id": buy.milk, "qty": "1.5", "unit_cost": "1000"}]
    r = buy.api.post("/api/v1/purchasing/invoices", frac, idem=new_key())
    assert r.get_json()["error"]["code"] == "fraction"

    make_user(app, "cash", ["CSH"])
    cash = login(app, "cash")
    assert cash.get("/api/v1/purchasing/invoices").status_code == 403
    assert (
        cash.post("/api/v1/purchasing/invoices", invoice_body(buy), idem=new_key()).status_code
        == 403
    )
    # The audit trail records the finalisation.
    with app.app_context():
        s = new_session()
        try:
            n = s.scalar(
                text(
                    "SELECT COUNT(*) FROM audit_event WHERE action = 'purchasing.invoice_finalized'"
                )
            )
        finally:
            s.close()
    assert n == 2
    assert Decimal(due[0]["supplier_balance"]) == Decimal("23316000")
