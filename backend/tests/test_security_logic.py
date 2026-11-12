"""Business-logic abuse at the register (security pass of 1405/08): quantities, amounts and
numbers an attacker or a broken client could send. Each one is refused with a clear
4xx or handled correctly, never a 500 and never a sale that does not add up.
"""

from __future__ import annotations

import uuid

import pytest
from flask import Flask

from tests.conftest import new_key
from tests.test_sales import Pos, login, open_shift, pos  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def _sale(pos: Pos, line: dict, payment: str = "110000", **kw: object) -> dict:  # noqa: F811
    return {
        "id": str(uuid.uuid4()),
        "cash_register_id": pos.r1,
        "lines": [{"item_id": pos.milk, **line}],
        "payments": [{"method": "cash", "amount": payment}],
        **kw,
    }


def test_hostile_quantities_and_amounts(app: Flask, pos: Pos) -> None:  # noqa: F811
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    for line in (
        {"qty": "-1"},
        {"qty": "0"},
        {"qty": "1.0001"},  # more decimals than a quantity holds
        {"qty": "1e3"},
        {"qty": "99999999999999999999999"},
        {"qty": "9999999999999"},  # fits a quantity, but qty × price overflows money
        {"qty": "NaN"},
        {"qty": "Infinity"},
        {"qty": "1", "manual_discount": "-5000"},
        {"qty": "1", "manual_discount": "999999999999"},  # more than the line itself
    ):
        for path in ("/api/v1/sales/quote", "/api/v1/sales/invoices"):
            r = c.post(path, _sale(pos, line), idem=new_key())
            assert 400 <= r.status_code < 500, (path, line, r.status_code, r.get_json())


def test_payment_and_number_tampering(app: Flask, pos: Pos) -> None:  # noqa: F811
    c = login(app, "cashier")
    open_shift(c, pos.r1)
    line = {"qty": "1"}
    for payment in ("-110000", "0", "1", "110000.00001", "1e30"):
        r = c.post("/api/v1/sales/invoices", _sale(pos, line, payment), idem=new_key())
        assert 400 <= r.status_code < 500, (payment, r.get_json())
    # The company's own number: length and characters are checked, never a 500.
    for number in ("x" * 500, "' OR 1=1--", "\x00", "<script>"):
        r = c.post("/api/v1/sales/invoices", _sale(pos, line, manual_number=number), idem=new_key())
        assert r.status_code < 500, (number[:20], r.get_json())
    # One idempotency key, a different body: the first answer, never a second sale.
    key = new_key()
    first = c.post("/api/v1/sales/invoices", _sale(pos, line), idem=key)
    assert first.status_code == 201, first.get_json()
    again = c.post("/api/v1/sales/invoices", _sale(pos, {"qty": "2"}, "220000"), idem=key)
    assert again.status_code in (409, 422) or again.get_json() == first.get_json()
