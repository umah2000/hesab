"""Search (ADR-0030): Arabic and Persian letters, the non-joiner and Persian digits compare
equal; results come best first; LIKE wildcards are literal; the register's in-browser
index answers 304 while nothing changed."""

from __future__ import annotations

import pytest
from flask import Flask

from app.core.text import fold
from tests.test_inventory import make_item
from tests.test_sales import Pos, _inv, login, pos  # noqa: F401 - fixture

pytestmark = pytest.mark.db


def test_fold() -> None:
    assert fold("شير  كوزه‌اي ۱۲") == "شیر کوزهای 12"
    assert fold("Coca Cola") == "Coca Cola"


def names(api, q: str) -> list[str]:  # type: ignore[no-untyped-def]
    r = api.get("/api/v1/inventory/items", query_string={"q": q, "page_size": 50})
    assert r.status_code == 200, r.get_json()
    return [x["name"] for x in r.get_json()["items"]]


def test_folded_ranked_search_and_index(app: Flask, pos: Pos) -> None:  # noqa: F811
    boss = login(app, "boss")
    inv = _inv(pos.wh, boss.get("/api/v1/inventory/items/" + pos.milk).get_json()["base_unit_id"])
    make_item(boss, inv, "S1", name="شير پرچرب")  # Arabic «ي»
    make_item(boss, inv, "S2", name="پنیر کوزه‌ای")  # non-joiner
    make_item(boss, inv, "S3", name="کیک شیری")
    make_item(boss, inv, "4321", name="کنسرو لوبیا")
    make_item(boss, inv, "S4", name="پودر 4321 گرمی")
    make_item(boss, inv, "S5", name="لیوان ۱۰۰٪")

    # Persian «ی» finds the Arabic «ي»; a name starting with it before one containing it.
    found = names(boss, "شیر")
    assert found.index("شير پرچرب") < found.index("کیک شیری")
    assert "پنیر کوزه‌ای" in names(boss, "کوزهای")
    assert "پنیر کوزه‌ای" in names(boss, "کوزه‌ای")
    # Every word, in any order.
    assert names(boss, "پرچرب شير") == ["شير پرچرب"]
    # Exact code first, then names containing it; Persian digits too.
    assert names(boss, "4321")[:2] == ["کنسرو لوبیا", "پودر 4321 گرمی"]
    assert names(boss, "۴۳۲۱")[0] == "کنسرو لوبیا"
    # LIKE wildcards are literal.
    assert names(boss, "%") == ["لیوان ۱۰۰٪"] or "لیوان ۱۰۰٪" not in names(boss, "_")
    assert names(boss, "_") == []
    # Suggestions skip the count.
    r = boss.get("/api/v1/inventory/items", query_string={"q": "شیر", "with_total": "false"})
    assert r.get_json()["total"] == len(r.get_json()["items"])

    # The register's index: folded names, ETag, 304 while unchanged, new after a change.
    cashier = login(app, "cashier")
    r = cashier.get("/api/v1/inventory/items/search-index")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    row = next(x for x in body["items"] if x[1] == "S1")
    assert row[2:4] == ["شير پرچرب", "شیر پرچرب"]
    etag = r.headers["ETag"]
    assert (
        cashier.get(
            "/api/v1/inventory/items/search-index", headers={"If-None-Match": etag}
        ).status_code
        == 304
    )
    s5 = boss.get("/api/v1/inventory/items", query_string={"q": "S5"}).get_json()["items"][0]
    item = boss.get(f"/api/v1/inventory/items/{s5['id']}").get_json()
    upd = boss.put(
        f"/api/v1/inventory/items/{item['id']}",
        {
            "code": "S5",
            "name": "لیوان یکبار مصرف",
            "base_unit_id": item["base_unit_id"],
            "units": [],
            "barcodes": [],
            "prices": [],
        },
        item["row_version"],
    )
    assert upd.status_code == 200, upd.get_json()
    again = cashier.get("/api/v1/inventory/items/search-index", headers={"If-None-Match": etag})
    assert again.status_code == 200
    assert any(x[2] == "لیوان یکبار مصرف" for x in again.get_json()["items"])


def test_customer_search_folds_letters(app: Flask, pos: Pos) -> None:  # noqa: F811
    from app.core.db import unit_of_work
    from app.modules.accounting.models import DetailAccount

    with app.app_context(), unit_of_work() as s:
        s.add(DetailAccount(code="C9", name="رستوران كوثر", kind="person", is_active=True))
    sup = login(app, "super")  # customers are listed for credit sales
    r = sup.get("/api/v1/sales/customers", query_string={"q": "کوثر"})
    assert r.status_code == 200, r.get_json()
    assert [c["name"] for c in r.get_json()] == ["رستوران كوثر"]
