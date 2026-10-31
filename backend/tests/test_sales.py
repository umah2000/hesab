"""POS: pricing, checkout, payments, approvals, shifts, returns, card reader, concurrency."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core import refcache
from app.core.db import new_session, unit_of_work
from app.modules.accounting.models import Account, DetailAccount, VoucherLine
from app.modules.accounting.services.chart import seed_defaults
from app.modules.accounting.services.fiscal import ensure_year
from app.modules.inventory.models import StockLedger, Unit, Warehouse
from app.modules.inventory.services.catalog import seed_catalog
from app.modules.inventory.services.stock import ensure_default_warehouses
from app.modules.organization.models import CashRegister, Organization
from tests.conftest import Api, Seed, make_user, new_key
from tests.test_inventory import D1, balance, ean, make_item, stock_doc

pytestmark = pytest.mark.db


@dataclass
class Pos:
    r1: str
    r2: str
    r_b: str
    wh: str
    milk: str
    bread: str
    cheese: str
    water: str
    pack: str
    kg: str


def login(app: Flask, username: str) -> Api:
    a = Api(app.test_client())
    assert a.login(username).status_code == 200
    return a


@pytest.fixture
def pos(app: Flask, seed: Seed) -> Pos:
    with app.app_context(), unit_of_work() as s:
        seed_defaults(s)
        ensure_year(s, 1405)
        seed_catalog(s)
        ensure_default_warehouses(s)
        # The amounts in these tests were written for VAT-inclusive prices and a 5 % cashier
        # limit; the shop's own defaults (exclusive, 0 %) are covered by
        # test_owner_defaults_vat_exclusive_and_no_cashier_discount.
        org = s.scalar(select(Organization))
        assert org is not None
        org.prices_include_vat, org.cashier_discount_limit = True, Decimal(5)
        regs = [
            CashRegister(branch_id=seed.branch_a, code="R1", name="صندوق ۱", is_active=True),
            CashRegister(branch_id=seed.branch_a, code="R2", name="صندوق ۲", is_active=True),
            CashRegister(branch_id=seed.branch_b, code="R1", name="صندوق شعبه دو", is_active=True),
        ]
        s.add_all(regs)
        s.flush()
        r1, r2, rb = (str(r.id) for r in regs)
        wh = str(s.scalar(select(Warehouse.id).where(Warehouse.branch_id == seed.branch_a)))
        units = {u.code: str(u.id) for u in s.scalars(select(Unit))}
        s.add(
            DetailAccount(
                code="C1",
                name="رستوران آفتاب",
                kind="person",
                is_active=True,
                credit_limit=Decimal(1_000_000),
            )
        )
    for name, roles in {
        "cashier": ["CSH"],
        "cashier2": ["CSH"],
        "super": ["SUP"],
        "boss": ["MGR", "ACC", "WHK"],
    }.items():
        make_user(app, name, roles, None if name == "boss" else [seed.branch_a])
    boss = login(app, "boss")
    pcs, kg = units["PCS"], units["KG"]
    rule = boss.post(
        "/api/v1/inventory/scale-rules",
        {
            "name": "ترازو",
            "prefix": "21",
            "item_code_length": 5,
            "value_length": 5,
            "value_type": "weight",
            "value_decimals": 3,
        },
        idem=new_key(),
    )
    assert rule.status_code == 201, rule.get_json()
    milk = make_item(
        boss,
        _inv(wh, pcs),
        "M1",
        barcodes=[{"barcode": ean("626100000001")}],
        prices=[{"unit_id": pcs, "price": "110000"}],
    )
    bread = make_item(
        boss, _inv(wh, pcs), "B1", vat_exempt=True, prices=[{"unit_id": pcs, "price": "50000"}]
    )
    cheese = make_item(
        boss,
        _inv(wh, kg),
        "CH",
        base_unit_id=kg,
        is_weighted=True,
        scale_code="00201",
        prices=[{"unit_id": kg, "price": "3900000"}],
    )
    water = make_item(
        boss,
        _inv(wh, pcs),
        "W1",
        units=[{"unit_id": units["PACK"], "factor": "6"}],
        prices=[{"unit_id": pcs, "price": "15000"}],
    )
    d = stock_doc(
        boss,
        "opening",
        wh,
        [
            {"item_id": milk["id"], "qty": "100", "unit_cost": "80000"},
            {"item_id": bread["id"], "qty": "50", "unit_cost": "30000"},
            {"item_id": cheese["id"], "qty": "10", "unit_cost": "3000000"},
            {"item_id": water["id"], "qty": "60", "unit_cost": "10000"},
        ],
        when=D1,
    )
    assert d["_status"] == 200, d
    return Pos(
        r1, r2, rb, wh, milk["id"], bread["id"], cheese["id"], water["id"], units["PACK"], kg
    )


def _inv(wh: str, unit: str):  # minimal stand-in for tests.test_inventory.Inv
    from tests.test_inventory import Inv

    return Inv(wh, wh, unit, unit, unit)


def open_shift(api: Api, register: str, cash: str = "0") -> dict:
    r = api.post(
        "/api/v1/sales/shifts/open",
        {"cash_register_id": register, "opening_cash": cash},
        idem=new_key(),
    )
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def sell(api: Api, register: str, lines: list[dict], payments: list[dict], **kw: object):
    body = {
        "id": str(uuid.uuid4()),
        "cash_register_id": register,
        "lines": lines,
        "payments": payments,
        **kw,
    }
    return api.post("/api/v1/sales/invoices", body, idem=new_key())


def voucher(app: Flask, voucher_id: str) -> dict[str, tuple[str, str]]:
    with app.app_context():
        s = new_session()
        try:
            rows = s.execute(
                select(Account.code, func.sum(VoucherLine.debit), func.sum(VoucherLine.credit))
                .join(Account, Account.id == VoucherLine.account_id)
                .where(VoucherLine.voucher_id == uuid.UUID(voucher_id))
                .group_by(Account.code)
            ).all()
            return {
                c: (format(d.normalize(), "f"), format(cr.normalize(), "f")) for c, d, cr in rows
            }
        finally:
            s.close()


# --- pricing and a plain sale ------------------------------------------------


def test_cash_sale_posts_stock_and_voucher(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    no_shift = sell(
        c, pos.r1, [{"item_id": pos.milk, "qty": "1"}], [{"method": "cash", "amount": "110000"}]
    )
    assert no_shift.get_json()["error"]["code"] == "no_open_shift"
    open_shift(c, pos.r1, "500000")

    q = c.post(
        "/api/v1/sales/quote",
        {
            "cash_register_id": pos.r1,
            "lines": [{"item_id": pos.milk, "qty": "2"}, {"item_id": pos.bread, "qty": "1"}],
        },
    ).get_json()
    assert (q["grand_total"], q["tax_total"], q["subtotal"]) == (
        "270000.0000",
        "20000.0000",
        "270000.0000",
    )
    assert q["lines"][1]["vat_exempt"] is True and q["lines"][1]["tax"] == "0.0000"

    r = sell(
        c,
        pos.r1,
        [{"item_id": pos.milk, "qty": "2"}, {"item_id": pos.bread, "qty": "1"}],
        [{"method": "cash", "amount": "270000"}],
        cash_tendered="300000",
    )
    assert r.status_code == 201, r.get_json()
    inv = r.get_json()
    assert inv["number"] == 1 and inv["status"] == "final" and inv["change_due"] == "30000.0000"
    assert voucher(app, inv["voucher_id"]) == {
        "1101": ("270000", "0"),
        "5101": ("0", "250000"),
        "3201": ("0", "20000"),
        "6101": ("190000", "0"),
        "1301": ("0", "190000"),
    }
    assert balance(app, pos.milk, pos.wh)[0] == "98.000"

    second = sell(
        c, pos.r1, [{"item_id": pos.bread, "qty": "1"}], [{"method": "cash", "amount": "50000"}]
    )
    assert second.get_json()["number"] == 2


def test_owner_defaults_vat_exclusive_and_no_cashier_discount(app: Flask, seed: Seed) -> None:
    """A fresh organization: shelf prices exclude VAT; cashiers give no manual discount."""
    with app.app_context():
        s = new_session()
        org = s.scalar(select(Organization))
        assert org is not None
        assert (org.prices_include_vat, org.cashier_discount_limit) == (False, Decimal(0))
        s.close()
    from app.modules.iam.permissions import SYSTEM_ROLES

    cashier = next(r for r in SYSTEM_ROLES if r.code == "CSH")
    assert "sales.invoice.discount" not in cashier.permissions


def test_cashier_manual_discount_needs_supervisor(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    lines = [{"item_id": pos.milk, "qty": "1"}]
    # 1 % — inside the 5 % limit, but the cashier role has no discount permission.
    refused = sell(c, pos.r1, lines, [{"method": "cash", "amount": "108900"}], discount="1100")
    assert refused.get_json()["error"]["code"] == "approval_required"
    ok = c.post(
        "/api/v1/sales/approvals",
        {
            "cash_register_id": pos.r1,
            "action": "discount_over_limit",
            "username": "super",
            "password": "Test-Passw0rd",
        },
    ).get_json()
    done = sell(
        c,
        pos.r1,
        lines,
        [{"method": "cash", "amount": "108900"}],
        discount="1100",
        approval_id=ok["id"],
    )
    assert done.status_code == 201, done.get_json()


def test_prices_exclusive_of_vat_setting(app: Flask, pos: Pos) -> None:
    with app.app_context(), unit_of_work() as s:
        org = s.scalar(select(Organization))
        assert org is not None
        refcache.invalidate_after_commit(s)
        org.prices_include_vat = False
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    q = c.post(
        "/api/v1/sales/quote",
        {"cash_register_id": pos.r1, "lines": [{"item_id": pos.milk, "qty": "1"}]},
    ).get_json()
    assert (q["tax_total"], q["grand_total"]) == ("11000.0000", "121000.0000")


def test_scale_label_and_pack_are_priced_on_server(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    label = ean("21" + "00201" + "01250")
    # The browser claims 0.001 kg; the server re-reads 1.250 kg from the label.
    q = c.post(
        "/api/v1/sales/quote",
        {
            "cash_register_id": pos.r1,
            "lines": [
                {"item_id": pos.cheese, "qty": "0.001", "barcode": label},
                {"item_id": pos.water, "unit_id": pos.pack, "qty": "2"},
            ],
        },
    ).get_json()
    cheese, pack = q["lines"]
    assert (cheese["qty"], cheese["gross"], cheese["tax"]) == (
        "1.250",
        "4875000.0000",
        "443182.0000",
    )
    # No pack price: 6 × base price.
    assert (pack["unit_price"], pack["gross"]) == ("90000.0000", "180000.0000")
    wrong = c.post(
        "/api/v1/sales/quote",
        {
            "cash_register_id": pos.r1,
            "lines": [{"item_id": pos.milk, "qty": "1", "barcode": label}],
        },
    )
    assert wrong.get_json()["error"]["code"] == "label_mismatch"
    frac = c.post(
        "/api/v1/sales/quote",
        {"cash_register_id": pos.r1, "lines": [{"item_id": pos.milk, "qty": "1.5"}]},
    )
    assert frac.get_json()["error"]["code"] == "fraction_qty"

    r = sell(
        c,
        pos.r1,
        [{"item_id": pos.water, "unit_id": pos.pack, "qty": "2"}],
        [{"method": "cash", "amount": "180000"}],
    )
    assert r.status_code == 201
    assert balance(app, pos.water, pos.wh)[0] == "48.000"


# --- discounts, promotions, approvals ----------------------------------------


def test_promotion_discount_limit_and_supervisor_approval(app: Flask, pos: Pos) -> None:
    boss = login(app, "boss")
    p = boss.post(
        "/api/v1/sales/promotions",
        {
            "name": "شیر ۱۰٪",
            "kind": "percent",
            "scope": "item",
            "item_id": pos.milk,
            "value": "10",
            "starts_on": "2026-01-01",
            "ends_on": "2027-12-31",
        },
        idem=new_key(),
    )
    assert p.status_code == 201, p.get_json()
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    lines = [{"item_id": pos.milk, "qty": "10"}]
    q = c.post(
        "/api/v1/sales/quote", {"cash_register_id": pos.r1, "lines": lines, "discount": "99000"}
    ).get_json()
    # 1,100,000 − 110,000 promotion − 99,000 manual (9% > 5% limit)
    assert (q["promotion_total"], q["manual_discount_total"], q["grand_total"]) == (
        "110000.0000",
        "99000.0000",
        "891000.0000",
    )
    assert q["needs_discount_approval"] is True
    pay = [{"method": "cash", "amount": "891000"}]
    refused = sell(c, pos.r1, lines, pay, discount="99000")
    assert refused.get_json()["error"]["code"] == "approval_required"

    bad = c.post(
        "/api/v1/sales/approvals",
        {
            "cash_register_id": pos.r1,
            "action": "discount_over_limit",
            "username": "super",
            "password": "wrong",
        },
    )
    assert bad.status_code == 401
    self_ok = c.post(
        "/api/v1/sales/approvals",
        {
            "cash_register_id": pos.r1,
            "action": "discount_over_limit",
            "username": "cashier",
            "password": "Test-Passw0rd",
        },
    )
    assert self_ok.status_code == 403
    ok = c.post(
        "/api/v1/sales/approvals",
        {
            "cash_register_id": pos.r1,
            "action": "discount_over_limit",
            "username": "super",
            "password": "Test-Passw0rd",
        },
    )
    assert ok.status_code == 201, ok.get_json()
    approval = ok.get_json()["id"]
    done = sell(c, pos.r1, lines, pay, discount="99000", approval_id=approval)
    assert done.status_code == 201, done.get_json()
    v = voucher(app, done.get_json()["voucher_id"])
    assert v["5103"] == ("209000", "0")  # promotion + manual discount
    assert v["1101"] == ("891000", "0")
    reused = sell(c, pos.r1, lines, pay, discount="99000", approval_id=approval)
    assert reused.get_json()["error"]["code"] == "approval_expired"


def test_line_removal_is_audited_and_needs_approval_for_cashier(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    body = {"cash_register_id": pos.r1, "item_id": pos.milk, "qty": "1", "line_total": "110000"}
    assert (
        c.post("/api/v1/sales/line-removals", body).get_json()["error"]["code"]
        == "approval_required"
    )
    a = c.post(
        "/api/v1/sales/approvals",
        {
            "cash_register_id": pos.r1,
            "action": "line_delete",
            "username": "super",
            "password": "Test-Passw0rd",
        },
    ).get_json()
    assert c.post("/api/v1/sales/line-removals", body | {"approval_id": a["id"]}).status_code == 201
    sup = login(app, "super")
    open_shift(sup, pos.r2)
    assert (
        sup.post("/api/v1/sales/line-removals", body | {"cash_register_id": pos.r2}).status_code
        == 201
    )
    with app.app_context():
        s = new_session()
        n = s.scalar(text("SELECT COUNT(*) FROM audit_event WHERE action = 'sales.line_removed'"))
        s.close()
    assert n == 2


# --- payments ------------------------------------------------------------------


def test_payment_rules_card_reference_and_credit_limit(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    line = [{"item_id": pos.milk, "qty": "1"}]
    assert (
        sell(c, pos.r1, line, [{"method": "cash", "amount": "100000"}]).get_json()["error"]["code"]
        == "payment_mismatch"
    )
    assert (
        sell(c, pos.r1, line, [{"method": "card", "amount": "110000"}]).get_json()["error"]["code"]
        == "card_reference_required"
    )
    split = sell(
        c,
        pos.r1,
        line,
        [
            {"method": "cash", "amount": "10000"},
            {"method": "card", "amount": "100000", "card_reference": "123456789012"},
        ],
    )
    assert split.status_code == 201
    assert voucher(app, split.get_json()["voucher_id"])["1104"] == ("100000", "0")
    # The cashier role has no credit sales.
    assert sell(c, pos.r1, line, [{"method": "credit", "amount": "110000"}]).status_code == 403

    sup = login(app, "super")
    open_shift(sup, pos.r2)
    with app.app_context():
        s = new_session()
        customer = str(s.scalar(select(DetailAccount.id).where(DetailAccount.code == "C1")))
        s.close()
    nine = [{"item_id": pos.milk, "qty": "9"}]
    ok = sell(sup, pos.r2, nine, [{"method": "credit", "amount": "990000"}], customer_id=customer)
    assert ok.status_code == 201, ok.get_json()
    assert voucher(app, ok.get_json()["voucher_id"])["1201"] == ("990000", "0")
    over = sell(sup, pos.r2, line, [{"method": "credit", "amount": "110000"}], customer_id=customer)
    assert over.get_json()["error"]["code"] == "credit_limit_exceeded"
    no_customer = sell(sup, pos.r2, line, [{"method": "credit", "amount": "110000"}])
    assert no_customer.get_json()["error"]["code"] == "customer_required"

    # Unlimited credit: no limit to exceed; a customer with neither still gets none.
    with app.app_context(), unit_of_work() as s:
        c1 = s.scalar(select(DetailAccount).where(DetailAccount.code == "C1"))
        assert c1 is not None
        c1.credit_limit, c1.credit_unlimited = None, True
        s.add(DetailAccount(code="C0", name="بدون نسیه", kind="person", is_active=True))
        s.flush()
        none_id = str(s.scalar(select(DetailAccount.id).where(DetailAccount.code == "C0")))
    big = [{"item_id": pos.milk, "qty": "5"}]
    free = sell(sup, pos.r2, big, [{"method": "credit", "amount": "550000"}], customer_id=customer)
    assert free.status_code == 201, free.get_json()
    listed = {c["code"]: c for c in sup.get("/api/v1/sales/customers?q=C").get_json()}
    assert listed["C1"]["credit_unlimited"] is True and listed["C1"]["available"] is None
    refused = sell(
        sup, pos.r2, line, [{"method": "credit", "amount": "110000"}], customer_id=none_id
    )
    assert refused.get_json()["error"]["code"] == "no_credit"


def test_checkout_is_idempotent_and_final_invoice_is_immutable(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    key = new_key()
    body = {
        "id": str(uuid.uuid4()),
        "cash_register_id": pos.r1,
        "lines": [{"item_id": pos.milk, "qty": "1"}],
        "payments": [{"method": "cash", "amount": "110000"}],
    }
    first = c.post("/api/v1/sales/invoices", body, idem=key)
    again = c.post("/api/v1/sales/invoices", body, idem=key)
    assert first.status_code == again.status_code == 201
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert balance(app, pos.milk, pos.wh)[0] == "99.000"
    other_key = c.post("/api/v1/sales/invoices", body, idem=new_key())
    assert other_key.get_json()["error"]["code"] == "invoice_exists"

    inv_id = first.get_json()["id"]
    with app.app_context():
        for sql in (
            "UPDATE sales_invoice SET grand_total = 1 WHERE id = :i",
            "DELETE FROM sales_payment WHERE invoice_id = :i",
            "UPDATE sales_invoice_line SET qty = 5 WHERE invoice_id = :i",
            "DELETE FROM sales_invoice WHERE id = :i",
        ):
            s = new_session()
            with pytest.raises(DBAPIError):
                s.execute(text(sql), {"i": inv_id})
                s.commit()
            s.rollback()
            s.close()


# --- negative stock -----------------------------------------------------------


def test_negative_stock_policy(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    many = [{"item_id": pos.bread, "qty": "60"}]
    q = c.post("/api/v1/sales/quote", {"cash_register_id": pos.r1, "lines": many}).get_json()
    assert q["warnings"] and "کافی نیست" in q["warnings"][0]
    warned = sell(c, pos.r1, many, [{"method": "cash", "amount": "3000000"}])
    assert warned.status_code == 201 and warned.get_json()["warnings"]
    assert balance(app, pos.bread, pos.wh)[0] == "-10.000"
    with app.app_context(), unit_of_work() as s:
        org = s.scalar(select(Organization))
        assert org is not None
        refcache.invalidate_after_commit(s)
        org.negative_stock_policy = "deny"
    denied = sell(
        c, pos.r1, [{"item_id": pos.bread, "qty": "1"}], [{"method": "cash", "amount": "50000"}]
    )
    assert denied.get_json()["error"]["code"] == "insufficient_stock"


# --- held carts ---------------------------------------------------------------


def test_hold_and_recall(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    h = c.post(
        "/api/v1/sales/held",
        {
            "cash_register_id": pos.r1,
            "lines": [{"item_id": pos.milk, "qty": "3"}],
            "note": "مشتری برگشت",
        },
        idem=new_key(),
    )
    assert h.status_code == 201 and h.get_json()["status"] == "held"
    other = login(app, "cashier2")
    open_shift(other, pos.r2)
    held = other.get(f"/api/v1/sales/held?cash_register_id={pos.r2}").get_json()
    assert [x["note"] for x in held] == ["مشتری برگشت"]
    rec = other.post(f"/api/v1/sales/held/{held[0]['id']}/recall")
    assert rec.status_code == 200 and rec.get_json()["lines"][0]["qty"] == "3.000"
    assert (
        c.post(f"/api/v1/sales/held/{held[0]['id']}/recall").get_json()["error"]["code"]
        == "not_held"
    )
    assert balance(app, pos.milk, pos.wh)[0] == "100.000"


# --- shift ----------------------------------------------------------------------


def test_shift_close_posts_shortage_and_report(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    sh = open_shift(c, pos.r1, "1000000")
    assert (
        c.post(
            "/api/v1/sales/shifts/open", {"cash_register_id": pos.r1}, idem=new_key()
        ).status_code
        == 409
    )
    other = login(app, "cashier2")
    busy = other.post("/api/v1/sales/shifts/open", {"cash_register_id": pos.r1}, idem=new_key())
    assert busy.get_json()["error"]["code"] == "register_busy"

    sell(c, pos.r1, [{"item_id": pos.milk, "qty": "2"}], [{"method": "cash", "amount": "220000"}])
    sell(
        c,
        pos.r1,
        [{"item_id": pos.bread, "qty": "1"}],
        [{"method": "card", "amount": "50000", "card_reference": "99887766"}],
    )
    rep = c.get(f"/api/v1/sales/shifts/{sh['id']}/report").get_json()
    assert (rep["sale_count"], rep["sales_total"], rep["expected_cash"]) == (
        2,
        "270000.0000",
        "1220000.0000",
    )

    closed = c.post(
        f"/api/v1/sales/shifts/{sh['id']}/close",
        {"counted_cash": "1200000"},
        headers={"If-Match": sh["row_version"]},
    )
    assert closed.status_code == 200, closed.get_json()
    out = closed.get_json()
    assert (out["difference"], out["status"]) == ("-20000.0000", "closed")
    assert voucher(app, out["voucher_id"]) == {"7107": ("20000", "0"), "1101": ("0", "20000")}
    after = sell(
        c, pos.r1, [{"item_id": pos.milk, "qty": "1"}], [{"method": "cash", "amount": "110000"}]
    )
    assert after.get_json()["error"]["code"] == "no_open_shift"


# --- returns --------------------------------------------------------------------


def test_returns_are_proportional_at_original_cost(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    sale = sell(
        c, pos.r1, [{"item_id": pos.milk, "qty": "3"}], [{"method": "cash", "amount": "330000"}]
    ).get_json()
    line = sale["lines"][0]
    # A later receipt at another cost must not change the cost the goods come back at.
    boss = login(app, "boss")
    stock_doc(
        boss,
        "adjustment",
        pos.wh,
        [{"item_id": pos.milk, "qty": "10", "unit_cost": "200000"}],
        when=__import__(
            "app.modules.inventory.services.stock", fromlist=["tehran_today"]
        ).tehran_today(),
    )

    body = {
        "cash_register_id": pos.r1,
        "lines": [{"original_line_id": line["id"], "qty": "1"}],
        "refunds": [{"method": "cash", "amount": "110000"}],
        "reason": "تاریخ گذشته",
    }
    # A cashier returns only with a supervisor's approval on the register (ADR-0029).
    refused = c.post(f"/api/v1/sales/invoices/{sale['id']}/returns", body, idem=new_key())
    assert refused.get_json()["error"]["code"] == "approval_required"
    sup = login(app, "super")
    open_shift(sup, pos.r2)
    body["cash_register_id"] = pos.r2
    r1 = sup.post(f"/api/v1/sales/invoices/{sale['id']}/returns", body, idem=new_key())
    assert r1.status_code == 201, r1.get_json()
    ret = r1.get_json()
    assert (ret["kind"], ret["number"], ret["grand_total"], ret["tax_total"]) == (
        "return",
        1,
        "110000.0000",
        "10000.0000",
    )
    assert voucher(app, ret["voucher_id"]) == {
        "5102": ("100000", "0"),
        "3201": ("10000", "0"),
        "1101": ("0", "110000"),
        "1301": ("80000", "0"),
        "6101": ("0", "80000"),
    }
    too_many = body | {
        "lines": [{"original_line_id": line["id"], "qty": "3"}],
        "refunds": [{"method": "cash", "amount": "330000"}],
    }
    assert (
        sup.post(
            f"/api/v1/sales/invoices/{sale['id']}/returns", too_many, idem=new_key()
        ).get_json()["error"]["code"]
        == "return_qty_exceeded"
    )
    rest = body | {
        "lines": [{"original_line_id": line["id"], "qty": "2"}],
        "refunds": [{"method": "cash"}],  # amount filled in by the server
    }
    done = sup.post(f"/api/v1/sales/invoices/{sale['id']}/returns", rest, idem=new_key())
    assert done.status_code == 201 and done.get_json()["grand_total"] == "220000.0000"
    detail = sup.get(f"/api/v1/sales/invoices/{sale['id']}").get_json()
    assert detail["lines"][0]["returned_qty"] == "3.000"
    # 100 − 3 + 10 + 3
    assert balance(app, pos.milk, pos.wh)[0] == "110.000"


# --- card reader ------------------------------------------------------------------


def test_card_reader_mock_unknown_requires_inquiry(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    cart = str(uuid.uuid4())
    start = {"cash_register_id": pos.r1, "cart_id": cart, "amount": "110000"}
    assert (
        c.post("/api/v1/payments/terminal-transactions", start).get_json()["error"]["code"]
        == "terminal_not_configured"
    )

    app.config["SETTINGS"].enable_mock_payment_terminal = True
    try:
        t = c.post(
            "/api/v1/payments/terminal-transactions", start | {"scenario": "timeout"}
        ).get_json()
        assert t["status"] == "Unknown" and t["is_simulated"] is True
        again = c.post("/api/v1/payments/terminal-transactions", start | {"scenario": "approve"})
        assert again.get_json()["error"]["code"] == "terminal_tx_unresolved"
        pay = [{"method": "card", "amount": "110000", "terminal_transaction_id": t["id"]}]
        body = {
            "id": cart,
            "cash_register_id": pos.r1,
            "lines": [{"item_id": pos.milk, "qty": "1"}],
            "payments": pay,
        }
        assert (
            c.post("/api/v1/sales/invoices", body, idem=new_key()).get_json()["error"]["code"]
            == "terminal_tx_not_approved"
        )
        inq = c.post(f"/api/v1/payments/terminal-transactions/{t['id']}/inquire").get_json()
        assert inq["status"] == "Approved" and inq["rrn"]
        done = c.post("/api/v1/sales/invoices", body, idem=new_key())
        assert done.status_code == 201, done.get_json()

        cart2 = str(uuid.uuid4())
        lost = c.post(
            "/api/v1/payments/terminal-transactions",
            start | {"cart_id": cart2, "scenario": "inquiry_unavailable"},
        ).get_json()
        lost = c.post(f"/api/v1/payments/terminal-transactions/{lost['id']}/inquire").get_json()
        assert lost["status"] == "ReconciliationRequired"
        close = c.post(
            f"/api/v1/sales/shifts/{c.get('/api/v1/sales/shifts').get_json()['items'][0]['id']}/close",
            {"counted_cash": "0"},
            headers={"If-Match": "x"},
        )
        assert close.status_code in (409, 422)
        boss = login(app, "boss")
        res = boss.post(
            f"/api/v1/payments/terminal-transactions/{lost['id']}/resolve",
            {"status": "Declined", "note": "در گزارش بانک نیست"},
            headers={"If-Match": lost["row_version"]},
        )
        assert res.status_code == 200 and res.get_json()["status"] == "Declined"
    finally:
        app.config["SETTINGS"].enable_mock_payment_terminal = False


# --- concurrency ----------------------------------------------------------------


def test_concurrent_registers_never_oversell_and_numbers_are_gap_free(
    app: Flask, pos: Pos, seed: Seed
) -> None:
    with app.app_context(), unit_of_work() as s:
        org = s.scalar(select(Organization))
        assert org is not None
        refcache.invalidate_after_commit(s)
        org.negative_stock_policy = "deny"
        for i in range(3, 8):
            s.add(
                CashRegister(
                    branch_id=seed.branch_a, code=f"R{i}", name=f"صندوق {i}", is_active=True
                )
            )
    with app.app_context():
        s = new_session()
        regs = [
            str(r)
            for r in s.scalars(
                select(CashRegister.id).where(CashRegister.branch_id == seed.branch_a)
            )
        ]
        s.close()
    clients = []
    for i, reg in enumerate(regs):
        make_user(app, f"c{i}", ["CSH"], [seed.branch_a])
        a = login(app, f"c{i}")
        open_shift(a, reg)
        clients.append((a, reg))
    # 50 bread in stock; 7 registers each try 4 sales of 2 → 56 wanted.
    results: list[int] = []
    lock = threading.Lock()

    def run(a: Api, reg: str) -> None:
        for _ in range(4):
            r = sell(
                a,
                reg,
                [{"item_id": pos.bread, "qty": "2"}],
                [{"method": "cash", "amount": "100000"}],
            )
            with lock:
                results.append(r.status_code)

    threads = [threading.Thread(target=run, args=ca) for ca in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(201) == 25, results
    assert balance(app, pos.bread, pos.wh)[0] == "0.000"
    with app.app_context():
        s = new_session()
        numbers = sorted(s.scalars(text("SELECT number FROM sales_invoice WHERE status = 'final'")))
        ledger = s.scalar(
            select(func.sum(StockLedger.qty_out)).where(StockLedger.item_id == uuid.UUID(pos.bread))
        )
        s.close()
    assert numbers == list(range(1, 26))
    assert ledger == Decimal(50)


def test_cashier_scope_and_permissions(app: Flask, pos: Pos) -> None:
    c = login(app, "cashier")
    other_branch = c.post(
        "/api/v1/sales/shifts/open", {"cash_register_id": pos.r_b}, idem=new_key()
    )
    assert other_branch.status_code == 404
    assert c.get("/api/v1/sales/reports/daily").status_code == 403
    boss = login(app, "boss")
    rep = boss.get("/api/v1/sales/reports/daily")
    assert rep.status_code == 200 and rep.get_json()["sale_count"] == 0


# --- acceptance: a whole business day ---------------------------------------------


def test_business_day_books_and_stock_agree(app: Flask, pos: Pos) -> None:
    """Open shifts → 200 sales on two registers → returns → close; then cross-check
    the stock ledger, the balances and the books (ROADMAP phase 4 acceptance)."""
    a, b = login(app, "cashier"), login(app, "cashier2")
    sh_a, sh_b = open_shift(a, pos.r1, "2000000"), open_shift(b, pos.r2, "1000000")
    label = ean("21" + "00201" + "00350")  # 0.350 kg cheese
    baskets = [
        ([{"item_id": pos.milk, "qty": "1"}], "110000"),
        ([{"item_id": pos.bread, "qty": "1"}, {"item_id": pos.milk, "qty": "1"}], "160000"),
        ([{"item_id": pos.cheese, "qty": "1", "barcode": label}], "1365000"),
        ([{"item_id": pos.water, "qty": "1"}], "15000"),
    ]
    sales: list[dict] = []
    for i in range(200):
        api, reg = (a, pos.r1) if i % 2 == 0 else (b, pos.r2)
        lines, total = baskets[i % len(baskets)]
        if i % 5 == 0:
            pay = [{"method": "card", "amount": total, "card_reference": f"{100000 + i}"}]
        elif i % 7 == 0 and Decimal(total) > 20000:
            cash = str(Decimal(total) - 10000)
            pay = [
                {"method": "cash", "amount": cash},
                {"method": "card", "amount": "10000", "card_reference": f"{200000 + i}"},
            ]
        else:
            pay = [{"method": "cash", "amount": total}]
        r = sell(api, reg, lines, pay)
        assert r.status_code == 201, (i, r.get_json())
        sales.append(r.get_json())
    assert [s["number"] for s in sales] == list(range(1, 201))

    sup = login(app, "super")
    # Return one milk from sale #2 (bread + milk) and the cheese of sale #3, in cash.
    a_ret = sales[1]
    milk_line = next(ln for ln in a_ret["lines"] if ln["item_id"] == pos.milk)
    ret_body = {
        "cash_register_id": pos.r2,
        "lines": [{"original_line_id": milk_line["id"], "qty": "1"}],
        "refunds": [{"method": "cash", "amount": "110000"}],
        "reason": "خراب",
    }
    rep_b = b.get(f"/api/v1/sales/shifts/{sh_b['id']}/report").get_json()
    closed_b = b.post(
        f"/api/v1/sales/shifts/{sh_b['id']}/close",
        {"counted_cash": rep_b["expected_cash"]},
        headers={"If-Match": sh_b["row_version"]},
    )
    assert closed_b.status_code == 200 and closed_b.get_json()["difference"] == "0.0000"
    sup_shift = open_shift(sup, pos.r2, "0")
    r = sup.post(f"/api/v1/sales/invoices/{a_ret['id']}/returns", ret_body, idem=new_key())
    assert r.status_code == 201, r.get_json()
    cheese_sale = sales[2]
    r2 = sup.post(
        f"/api/v1/sales/invoices/{cheese_sale['id']}/returns",
        {
            "cash_register_id": pos.r2,
            "lines": [{"original_line_id": cheese_sale["lines"][0]["id"], "qty": "0.350"}],
            "refunds": [{"method": "cash", "amount": "1365000"}],
            "reason": "مشتری نخواست",
        },
        idem=new_key(),
    )
    assert r2.status_code == 201, r2.get_json()

    rep_a = a.get(f"/api/v1/sales/shifts/{sh_a['id']}/report").get_json()
    assert rep_a["sale_count"] == 100
    assert (
        a.post(
            f"/api/v1/sales/shifts/{sh_a['id']}/close",
            {"counted_cash": rep_a["expected_cash"]},
            headers={"If-Match": sh_a["row_version"]},
        ).status_code
        == 200
    )
    rep_s = sup.get(f"/api/v1/sales/shifts/{sup_shift['id']}/report").get_json()
    assert (rep_s["return_count"], rep_s["expected_cash"]) == (2, "-1475000.0000")

    # Stock: 50 baskets of each kind.
    assert balance(app, pos.milk, pos.wh)[0] == "1.000"  # 100 − 50 − 50 + 1
    assert balance(app, pos.bread, pos.wh)[0] == "0.000"  # 50 − 50
    assert balance(app, pos.cheese, pos.wh)[0] == "-7.150"  # 10 − 50×0.35 + 0.35 (warn policy)
    assert balance(app, pos.water, pos.wh)[0] == "10.000"

    with app.app_context():
        s = new_session()
        try:
            # Every voucher balances, and the books agree with the stock and the drawer.
            unbalanced = s.scalar(
                text(
                    "SELECT COUNT(*) FROM voucher "
                    "WHERE status = 'final' AND total_debit <> total_credit"
                )
            )
            assert unbalanced == 0
            acc = {
                code: Decimal(v or 0)
                for code, v in s.execute(
                    text(
                        "SELECT a.code, SUM(l.debit - l.credit) FROM voucher_line l "
                        "JOIN voucher v ON v.id = l.voucher_id AND v.status = 'final' "
                        "JOIN account a ON a.id = l.account_id GROUP BY a.code"
                    )
                ).all()
            }
            stock_value = s.scalar(text("SELECT SUM(value) FROM stock_balance"))
            ledger_qty = {
                str(i).lower(): q
                for i, q in s.execute(
                    text("SELECT item_id, SUM(qty_in - qty_out) FROM stock_ledger GROUP BY item_id")
                ).all()
            }
            cash_sales = s.scalar(
                text(
                    "SELECT SUM(CASE WHEN i.kind = 'sale' THEN p.amount ELSE -p.amount END) "
                    "FROM sales_payment p JOIN sales_invoice i ON i.id = p.invoice_id "
                    "WHERE p.method = 'cash' AND i.status = 'final'"
                )
            )
        finally:
            s.close()
    assert acc["1301"] == stock_value
    assert acc["1101"] == cash_sales
    assert ledger_qty[pos.milk] == Decimal(1)
    sales_total = sum(Decimal(x["grand_total"]) for x in sales)
    assert acc["5101"] + acc["3201"] + acc.get("5103", Decimal(0)) + acc["5102"] == -(
        sales_total - Decimal(1475000)
    )


def test_stock_screens_show_sales_documents(app: Flask, pos: Pos) -> None:
    """Found by the phase 10 volume test: kardex and the stock document list failed once
    a sale had created its stock document (output schema allowed manual types only)."""
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    sale = sell(
        c, pos.r1, [{"item_id": pos.milk, "qty": "2"}], [{"method": "cash", "amount": "220000"}]
    )
    assert sale.status_code == 201, sale.get_json()
    make_user(app, "stockview", ["MGR", "WHK"])
    m = login(app, "stockview")
    k = m.get(f"/api/v1/inventory/kardex?item_id={pos.milk}&warehouse_id={pos.wh}")
    assert k.status_code == 200, k.get_json()
    assert "sale" in {r["doc_type"] for r in k.get_json()["items"]}
    docs = m.get("/api/v1/inventory/stock-documents?page_size=50")
    assert docs.status_code == 200, docs.get_json()
    sale_doc = next(d for d in docs.get_json()["items"] if d["doc_type"] == "sale")
    assert m.get(f"/api/v1/inventory/stock-documents/{sale_doc['id']}").status_code == 200


def test_several_card_readers_chosen_at_payment(app: Flask, pos: Pos) -> None:
    """ADR-0023: readers are defined per branch, a register has a default, the cashier
    picks one; a provider without a driver is listed with the reason, never sent to."""
    from app.modules.organization.models import CashRegister

    with app.app_context(), unit_of_work() as s:
        r1 = s.get(CashRegister, uuid.UUID(pos.r1))
        rb = s.get(CashRegister, uuid.UUID(pos.r_b))
        assert r1 is not None and rb is not None
        branch, other = str(r1.branch_id), str(rb.branch_id)
    boss = login(app, "boss")
    sep = {
        "name": "سامان صندوق ۱",
        "provider": "sep",
        "host": "192.168.1.105",
        "branch_id": branch,
        "cash_register_id": pos.r1,
    }
    a = boss.post("/api/v1/payments/terminals", sep)
    assert a.status_code == 201, a.get_json()
    assert a.json["driver_ready"] is False and "SSP1126" in a.json["driver_note"]
    assert (
        boss.post("/api/v1/payments/terminals", sep).json["error"]["code"] == "terminal_name_taken"
    )
    wrong = boss.post(
        "/api/v1/payments/terminals", sep | {"name": "x1", "cash_register_id": pos.r_b}
    )
    assert wrong.json["error"]["code"] == "register_branch_mismatch"
    bad_host = boss.post("/api/v1/payments/terminals", sep | {"name": "x2", "host": "a b;c"})
    assert bad_host.status_code == 400
    # A mock reader is for development only.
    mock = sep | {"name": "آزمایشی", "provider": "mock", "cash_register_id": None}
    assert (
        boss.post("/api/v1/payments/terminals", mock).json["error"]["code"] == "mock_in_production"
    )
    app.config["SETTINGS"].enable_mock_payment_terminal = True
    try:
        m = boss.post("/api/v1/payments/terminals", mock).get_json()
        far = boss.post(
            "/api/v1/payments/terminals", mock | {"name": "شعبه ب", "branch_id": other}
        ).get_json()

        c = login(app, "cashier")
        assert c.post("/api/v1/payments/terminals", sep | {"name": "x3"}).status_code == 403
        open_shift(c, pos.r1)
        state = c.get(f"/api/v1/sales/registers/{pos.r1}/state").get_json()
        listed = [(t["name"], t["is_default"], t["ready"]) for t in state["terminals"]]
        # This register's default first; the other branch's reader is not offered.
        assert listed == [("سامان صندوق ۱", True, False), ("آزمایشی", False, True)]
        assert "SSP1126" in state["terminals"][0]["reason"]

        cart = str(uuid.uuid4())
        start = {"cash_register_id": pos.r1, "cart_id": cart, "amount": "110000"}
        no_driver = c.post(
            "/api/v1/payments/terminal-transactions", start | {"terminal_id": a.json["id"]}
        )
        assert no_driver.json["error"]["code"] == "terminal_driver_unavailable"
        elsewhere = c.post(
            "/api/v1/payments/terminal-transactions", start | {"terminal_id": far["id"]}
        )
        assert elsewhere.status_code == 404
        t = c.post(
            "/api/v1/payments/terminal-transactions",
            start | {"terminal_id": m["id"], "scenario": "timeout"},
        ).get_json()
        assert t["terminal_id"] == m["id"] and t["status"] == "Unknown"
        inq = c.post(f"/api/v1/payments/terminal-transactions/{t['id']}/inquire").get_json()
        assert inq["status"] == "Approved"

        # Switched off: no longer offered, and an open attempt goes to reconciliation.
        off = boss.put(
            f"/api/v1/payments/terminals/{m['id']}", mock | {"is_active": False}, m["row_version"]
        )
        assert off.status_code == 200 and off.json["driver_ready"] is False
        names = [
            x["name"] for x in c.get(f"/api/v1/sales/registers/{pos.r1}/state").json["terminals"]
        ]
        assert names == ["سامان صندوق ۱"]
        listed_all = boss.get("/api/v1/payments/terminals").get_json()
        assert {x["name"] for x in listed_all} == {"سامان صندوق ۱", "آزمایشی", "شعبه ب"}
    finally:
        app.config["SETTINGS"].enable_mock_payment_terminal = False


def test_sep_central_reader_pays_in_the_background(app: Flask, pos: Pos) -> None:
    """ADR-0024: the attempt is saved as Pending with SEP's Identifier, the device is
    called after the response, the register polls; cancel and inquiry never overwrite a
    different final answer. Against the stand-in in tests/sep_fake.py, not Saman."""
    import time

    from pydantic import SecretStr

    from app.modules.sales.services import sep_pcpos
    from tests.sep_fake import CLIENT, USER, FakeSep, approved, fail

    with app.app_context(), unit_of_work() as s:
        r1 = s.get(CashRegister, uuid.UUID(pos.r1))
        assert r1 is not None
        branch = str(r1.branch_id)
    boss = login(app, "boss")
    reader = {
        "name": "سامان مرکزی ۱",
        "provider": "sep_central",
        "branch_id": branch,
        "cash_register_id": pos.r1,
    }
    no_terminal = boss.post("/api/v1/payments/terminals", reader)
    assert no_terminal.json["error"]["code"] == "terminal_no_required"
    made = boss.post("/api/v1/payments/terminals", reader | {"terminal_no": "1371"})
    assert made.status_code == 201, made.get_json()
    assert made.json["driver_ready"] is False
    assert "NEXTCAM_SEP_PCPOS_URL" in made.json["driver_note"]

    fake = FakeSep()
    sep_pcpos._tokens.clear()
    settings = app.config["SETTINGS"]
    before = {k: getattr(settings, k) for k in type(settings).model_fields if "sep_" in k}
    settings.sep_pcpos_url = settings.sep_pcpos_identity_url = fake.url
    settings.sep_pcpos_client_id, settings.sep_pcpos_username = CLIENT[0], USER[0]
    settings.sep_pcpos_client_secret = SecretStr(CLIENT[1])
    settings.sep_pcpos_password = SecretStr(USER[1])
    try:
        assert "https" in boss.get("/api/v1/payments/terminals").json[0]["driver_note"]
        settings.sep_pcpos_allow_http = True
        listed = boss.get("/api/v1/payments/terminals").json
        assert [(t["name"], t["driver_ready"]) for t in listed] == [("سامان مرکزی ۱", True)]

        c = login(app, "cashier")
        open_shift(c, pos.r1)
        state = c.get(f"/api/v1/sales/registers/{pos.r1}/state").json
        assert [(t["name"], t["ready"]) for t in state["terminals"]] == [("سامان مرکزی ۱", True)]

        def wait(tx_id: str) -> dict:
            for _ in range(100):
                t = c.get(f"/api/v1/payments/terminal-transactions/{tx_id}").get_json()
                if t["status"] != "Pending":
                    return t
                time.sleep(0.05)
            raise AssertionError("still pending")

        cart = str(uuid.uuid4())
        start = {
            "cash_register_id": pos.r1,
            "cart_id": cart,
            "amount": "110000",
            "terminal_id": made.json["id"],
        }
        frac = c.post("/api/v1/payments/terminal-transactions", start | {"amount": "110000.5"})
        assert frac.json["error"]["code"] == "terminal_amount_fraction"

        fake.pay_delay = 0.3
        t = c.post("/api/v1/payments/terminal-transactions", start)
        assert t.status_code == 201 and t.json["status"] == "Pending"
        # Still at the device: an inquiry does not ask SEP anything yet.
        mid = c.post(f"/api/v1/payments/terminal-transactions/{t.json['id']}/inquire").json
        assert mid["status"] == "Pending"
        done = wait(t.json["id"])
        assert (done["status"], done["rrn"], done["message"]) == (
            "Approved",
            "802151113805",
            "تراکنش با موفقیت انجام پذیرفت",
        )
        assert "Inquery" not in fake.ops()
        pay_body = next(x.body for x in fake.calls if x.path.endswith("/StartPayment"))
        assert pay_body["Amount"] == "110000" and pay_body["TerminalID"] == "1371"
        assert pay_body["ResNum"] == uuid.UUID(done["request_id"]).hex
        sale = {
            "id": cart,
            "cash_register_id": pos.r1,
            "lines": [{"item_id": pos.milk, "qty": "1"}],
            "payments": [
                {"method": "card", "amount": "110000", "terminal_transaction_id": done["id"]}
            ],
        }
        paid = c.post("/api/v1/sales/invoices", sale, idem=new_key())
        assert paid.status_code == 201, paid.get_json()

        # Declined by the card's bank: the message comes from SEP's table.
        fake.pay_delay = 0
        fake.pay = lambda body: (200, fail(51, "insufficient"))
        cart2 = str(uuid.uuid4())
        d = wait(
            c.post("/api/v1/payments/terminal-transactions", start | {"cart_id": cart2}).json["id"]
        )
        assert (d["status"], d["response_code"], d["message"]) == (
            "Declined",
            "51",
            "موجودی کافی نیست",
        )

        # The customer walks away: the cashier cancels while the device waits.
        fake.pay_delay = 1.0
        fake.pay = lambda body: (200, fail(98, "لغو عملیات توسط کاربر"))
        fake.inquiry = lambda body: (200, fail(98, "لغو عملیات توسط کاربر"))
        w = c.post("/api/v1/payments/terminal-transactions", start | {"cart_id": cart2}).json
        cancelled = c.post(f"/api/v1/payments/terminal-transactions/{w['id']}/cancel").json
        assert cancelled["status"] == "Declined"
        assert fake.calls[-1].body["CancelPendingRequest"] is True
        time.sleep(1.3)
        assert wait(w["id"])["status"] == "Declined"

        # No answer in time: Unknown, then the inquiry finds it approved.
        settings.sep_pcpos_timeout_seconds = 1
        fake.pay_delay = 2.0
        fake.pay = None
        fake.inquiry = lambda body: (200, approved(body, amount="110000"))
        cart3 = str(uuid.uuid4())
        u = wait(
            c.post("/api/v1/payments/terminal-transactions", start | {"cart_id": cart3}).json["id"]
        )
        assert (u["status"], u["response_code"]) == ("Unknown", "NOANSWER")
        again = c.post("/api/v1/payments/terminal-transactions", start | {"cart_id": cart3})
        assert again.json["error"]["code"] == "terminal_tx_unresolved"
        inq = c.post(f"/api/v1/payments/terminal-transactions/{u['id']}/inquire").json
        assert inq["status"] == "Approved"
        assert fake.calls[-1].body["CancelPendingRequest"] is False
        time.sleep(1.2)  # the late device answer (approved too) changes nothing

        # Two sends for one cart at once (double click, two tabs): one reaches the device.
        settings.sep_pcpos_timeout_seconds = 100
        fake.pay_delay, fake.ident_delay, fake.inquiry = 0.0, 0.5, None
        cart4, results = str(uuid.uuid4()), []
        sent = sum(1 for x in fake.calls if x.path.endswith("/StartPayment"))
        tills = [login(app, "cashier"), login(app, "cashier")]

        def send(till: Api) -> None:
            r = till.post("/api/v1/payments/terminal-transactions", start | {"cart_id": cart4})
            results.append(r.status_code)

        threads = [threading.Thread(target=send, args=(t,)) for t in tills]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert sorted(results) == [201, 409]
        time.sleep(0.3)
        assert sum(1 for x in fake.calls if x.path.endswith("/StartPayment")) == sent + 1
        fake.ident_delay = 0.0

        # The service is down before anything is sent: no attempt is recorded.
        fake.close()
        down = c.post(
            "/api/v1/payments/terminal-transactions", start | {"cart_id": str(uuid.uuid4())}
        )
        assert down.json["error"]["code"] == "terminal_unreachable"
    finally:
        for k, v in before.items():
            setattr(settings, k, v)
        fake.close()


def test_shop_scale_label_shelf_tickets_and_receipt_prices(app: Flask, pos: Pos) -> None:
    """The shop's samples (1405/08/02): a scale label of 12 digits without check digit
    (250212001442 = PLU 02120, 1.442 kg), eggs at 3,400,000 sold at 2,580,000 a kilo;
    the receipt's shop price and amount, and the shelf ticket, from the server."""
    from tests.test_inventory import make_item

    boss = login(app, "boss")
    rule = boss.post(
        "/api/v1/inventory/scale-rules",
        {
            "name": "ترازوی فروشگاه",
            "prefix": "25",
            "item_code_length": 5,
            "value_length": 5,
            "value_type": "weight",
            "value_decimals": 3,
            "check_digit": False,
        },
        idem=new_key(),
    )
    assert rule.status_code == 201 and rule.json["check_digit"] is False, rule.get_json()
    eggs = make_item(
        boss,
        _inv(pos.wh, pos.kg),
        "EGG",
        name="تخم مرغ",
        base_unit_id=pos.kg,
        is_weighted=True,
        scale_code="02120",
        prices=[{"unit_id": pos.kg, "price": "3400000"}],
    )
    # A normal product barcode can no longer take this shape.
    clash = boss.post(
        "/api/v1/inventory/items",
        {
            "code": "X12",
            "name": "کالای آزمایشی",
            "base_unit_id": pos.kg,
            "barcodes": [{"barcode": "250000000001"}],
        },
        idem=new_key(),
    )
    assert clash.json["error"]["code"] == "barcode_scale_prefix"
    promo = boss.post(
        "/api/v1/sales/promotions",
        {
            "name": "تخم مرغ ویژه",
            "kind": "amount",
            "scope": "item",
            "item_id": eggs["id"],
            "value": "820000",
            "starts_on": "2026-01-01",
            "ends_on": "2027-12-31",
        },
        idem=new_key(),
    )
    assert promo.status_code == 201, promo.get_json()

    c = login(app, "cashier")
    open_shift(c, pos.r1)
    q = c.post(
        "/api/v1/sales/quote",
        {
            "cash_register_id": pos.r1,
            "lines": [{"item_id": eggs["id"], "qty": "1", "barcode": "250212001442"}],
        },
    ).get_json()
    line = q["lines"][0]
    assert (line["qty"], line["gross"], line["promotion_discount"]) == (
        "1.442",
        "4902800.0000",
        "1182440.0000",
    )
    assert (line["net_amount"], line["net_unit_price"]) == ("3720360.0000", "2580000.0000")

    tickets = boss.post("/api/v1/sales/price-tickets", {"item_ids": [eggs["id"], pos.milk]})
    assert tickets.status_code == 200, tickets.get_json()
    by_code = {t["code"]: t for t in tickets.json["tickets"]}
    egg = by_code["EGG"]
    assert (egg["price"], egg["final_price"], egg["discount_percent"]) == (
        "3400000.0000",
        "2580000.0000",
        "24.12",
    )
    assert egg["is_weighted"] is True and egg["unit_name"] == "کیلوگرم"
    assert (by_code["M1"]["discount_percent"], by_code["M1"]["final_price"]) == (
        None,
        "110000.0000",
    )
    promoted = boss.post("/api/v1/sales/price-tickets", {"promoted_only": True}).json
    assert [t["code"] for t in promoted["tickets"]] == ["EGG"]
    none = boss.post("/api/v1/sales/price-tickets", {})
    assert none.json["error"]["code"] == "no_items"
    assert c.post("/api/v1/sales/price-tickets", {"item_ids": [pos.milk]}).status_code == 403
