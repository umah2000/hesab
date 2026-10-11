"""Items, barcodes, scale labels, stock documents, moving average, Excel import."""

from __future__ import annotations

import io
import threading
import uuid
from dataclasses import dataclass
from datetime import date

import pytest
from flask import Flask
from openpyxl import Workbook
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import new_session, unit_of_work
from app.modules.accounting.services.chart import seed_defaults
from app.modules.accounting.services.fiscal import ensure_year
from app.modules.inventory.models import StockBalance, Unit, Warehouse
from app.modules.inventory.services.catalog import ean13_check_digit, seed_catalog
from app.modules.inventory.services.stock import ensure_default_warehouses
from tests.conftest import Api, Seed, make_user, new_key

pytestmark = pytest.mark.db

D1 = date(2026, 4, 1)
D2 = date(2026, 5, 1)
D3 = date(2026, 6, 1)


@dataclass
class Inv:
    wh_a: str
    wh_b: str
    pcs: str
    kg: str
    ctn: str


@pytest.fixture
def inv(app: Flask, seed: Seed) -> Inv:
    with app.app_context(), unit_of_work() as s:
        seed_defaults(s)
        ensure_year(s, 1405)
        seed_catalog(s)
        ensure_default_warehouses(s)
        wh = {w.branch_id: str(w.id) for w in s.scalars(select(Warehouse))}
        units = {u.code: str(u.id) for u in s.scalars(select(Unit))}
    return Inv(wh[seed.branch_a], wh[seed.branch_b], units["PCS"], units["KG"], units["CTN"])


@pytest.fixture
def keeper(app: Flask, seed: Seed) -> Api:
    make_user(app, "keeper", ["WHK", "MGR", "ACC"])
    a = Api(app.test_client())
    assert a.login("keeper").status_code == 200
    return a


def make_item(api: Api, inv: Inv, code: str, **kw: object) -> dict:
    body = {"code": code, "name": f"کالا {code}", "base_unit_id": inv.pcs, **kw}
    r = api.post("/api/v1/inventory/items", body, idem=new_key())
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def stock_doc(
    api: Api,
    doc_type: str,
    wh: str,
    lines: list[dict],
    when: date = D1,
    dest: str | None = None,
    finalize: bool = True,
) -> dict:
    body = {
        "doc_type": doc_type,
        "warehouse_id": wh,
        "document_date": when.isoformat(),
        "lines": lines,
    }
    if dest:
        body["dest_warehouse_id"] = dest
    r = api.post("/api/v1/inventory/stock-documents", body, idem=new_key())
    assert r.status_code == 201, r.get_json()
    d = r.get_json()
    if not finalize:
        return d
    f = api.post(
        f"/api/v1/inventory/stock-documents/{d['id']}/finalize",
        headers={"If-Match": d["row_version"]},
    )
    return f.get_json() | {"_status": f.status_code}


def balance(app: Flask, item: str, wh: str) -> tuple[str, str, str]:
    with app.app_context():
        s = new_session()
        try:
            b = s.get(StockBalance, (uuid.UUID(item), uuid.UUID(wh)))
            return (
                (format(b.qty, "f"), format(b.value, "f"), format(b.avg_cost.normalize(), "f"))
                if b
                else ("0", "0", "0")
            )
        finally:
            s.close()


def ean(first12: str) -> str:
    return first12 + str(ean13_check_digit(first12))


# --- catalog ------------------------------------------------------------------


def test_item_barcodes_prices_and_lookup(keeper: Api, inv: Inv) -> None:
    it = make_item(
        keeper,
        inv,
        "1001",
        name="شیر پرچرب ۱ لیتری",
        units=[{"unit_id": inv.ctn, "factor": "12"}],
        barcodes=[{"barcode": "6260100212345"}, {"barcode": "6260100212352", "unit_id": inv.ctn}],
        prices=[{"price": "420000"}, {"unit_id": inv.ctn, "price": "4800000"}],
    )
    assert it["stock_qty"] == "0.000"
    single = keeper.get("/api/v1/inventory/items/lookup?barcode=6260100212345").get_json()
    assert single["source"] == "barcode" and single["qty"] == "1.000"
    assert single["line_price"] == "420000.0000"
    pack = keeper.get("/api/v1/inventory/items/lookup?barcode=6260100212352").get_json()
    assert pack["source"] == "pack_barcode" and pack["unit_price"] == "4800000.0000"
    # Scanner on a Persian keyboard layout sends Persian digits.
    fa = keeper.get("/api/v1/inventory/items/lookup?barcode=۶۲۶۰۱۰۰۲۱۲۳۴۵").get_json()
    assert fa["item_id"] == it["id"]
    found = keeper.get("/api/v1/inventory/items?q=۶۲۶۰۱۰۰۲۱۲۳۴۵").get_json()
    assert found["total"] == 1
    missing = keeper.get("/api/v1/inventory/items/lookup?barcode=1234567890128")
    assert missing.status_code == 404


def test_barcode_uniqueness(keeper: Api, inv: Inv) -> None:
    make_item(keeper, inv, "A1", barcodes=[{"barcode": "111222333"}])
    clash = keeper.post(
        "/api/v1/inventory/items",
        {
            "code": "A2",
            "name": "دیگری",
            "base_unit_id": inv.pcs,
            "barcodes": [{"barcode": "111222333"}],
        },
        idem=new_key(),
    )
    assert clash.status_code == 409
    assert clash.get_json()["error"]["code"] == "barcode_taken"


def test_scale_barcodes(keeper: Api, inv: Inv) -> None:
    rule = keeper.post(
        "/api/v1/inventory/scale-rules",
        {
            "name": "ترازو وزنی",
            "prefix": "21",
            "item_code_length": 5,
            "value_length": 5,
            "value_type": "weight",
            "value_decimals": 3,
        },
        idem=new_key(),
    )
    assert rule.status_code == 201, rule.get_json()
    keeper.post(
        "/api/v1/inventory/scale-rules",
        {
            "name": "ترازو قیمتی",
            "prefix": "22",
            "item_code_length": 5,
            "value_length": 5,
            "value_type": "price",
            "value_decimals": 1,
        },
        idem=new_key(),
    )
    overlap = keeper.post(
        "/api/v1/inventory/scale-rules",
        {
            "name": "xx",
            "prefix": "2",
            "item_code_length": 6,
            "value_length": 5,
            "value_type": "weight",
        },
        idem=new_key(),
    )
    assert overlap.get_json()["error"]["code"] == "prefix_overlap"
    bad_len = keeper.post(
        "/api/v1/inventory/scale-rules",
        {
            "name": "xx",
            "prefix": "23",
            "item_code_length": 5,
            "value_length": 4,
            "value_type": "weight",
        },
        idem=new_key(),
    )
    assert bad_len.get_json()["error"]["code"] == "invalid_rule"

    make_item(
        keeper,
        inv,
        "MEAT",
        name="گوشت چرخ‌کرده",
        base_unit_id=inv.kg,
        is_weighted=True,
        scale_code="123",
        prices=[{"price": "8900000"}],
    )
    weight = keeper.get(f"/api/v1/inventory/items/lookup?barcode={ean('210012301250')}").get_json()
    assert weight["source"] == "scale_weight" and weight["qty"] == "1.250"
    assert weight["line_price"] == "11125000.0000"
    # Label price 1,112,500 toman printed as 5 digits ×10 → here 11125 → 111250 rials.
    price = keeper.get(f"/api/v1/inventory/items/lookup?barcode={ean('220012311125')}").get_json()
    assert price["source"] == "scale_price" and price["line_price"] == "111250.0000"
    good = ean("210012301250")
    tampered = good[:12] + str((int(good[12]) + 1) % 10)
    wrong_check = keeper.get(f"/api/v1/inventory/items/lookup?barcode={tampered}")
    assert wrong_check.get_json()["error"]["code"] == "bad_check_digit"
    clash = keeper.post(
        "/api/v1/inventory/items",
        {
            "code": "X",
            "name": "کالا",
            "base_unit_id": inv.pcs,
            "barcodes": [{"barcode": ean("219999900000")}],
        },
        idem=new_key(),
    )
    assert clash.get_json()["error"]["code"] == "barcode_scale_prefix"


# --- stock & costing ---------------------------------------------------------


def test_opening_posts_stock_and_voucher(app: Flask, keeper: Api, inv: Inv) -> None:
    a = make_item(keeper, inv, "1001")
    b = make_item(keeper, inv, "1002", units=[{"unit_id": inv.ctn, "factor": "24"}])
    doc = stock_doc(
        keeper,
        "opening",
        inv.wh_a,
        [
            {"item_id": a["id"], "qty": "10", "unit_cost": "1000"},
            {"item_id": b["id"], "unit_id": inv.ctn, "qty": "2", "unit_cost": "240000"},
        ],
    )
    assert doc["_status"] == 200, doc
    assert doc["status"] == "final" and doc["number"] == 1 and doc["voucher_number"] == 1
    assert doc["total_value"] == "490000.0000"
    assert balance(app, a["id"], inv.wh_a) == ("10.000", "10000.0000", "1000")
    assert balance(app, b["id"], inv.wh_a) == ("48.000", "480000.0000", "10000")
    v = keeper.get(f"/api/v1/accounting/vouchers/{doc['voucher_id']}").get_json()
    assert {(ln["account_code"], ln["debit"], ln["credit"]) for ln in v["lines"]} == {
        ("1301", "490000.0000", "0.0000"),
        ("4101", "0.0000", "490000.0000"),
    }


def test_moving_average_and_adjustment_voucher(app: Flask, keeper: Api, inv: Inv) -> None:
    it = make_item(keeper, inv, "2001")
    stock_doc(
        keeper, "opening", inv.wh_a, [{"item_id": it["id"], "qty": "10", "unit_cost": "1000"}], D1
    )
    surplus = stock_doc(
        keeper,
        "adjustment",
        inv.wh_a,
        [{"item_id": it["id"], "qty": "10", "unit_cost": "2000"}],
        D2,
    )
    assert balance(app, it["id"], inv.wh_a) == ("20.000", "30000.0000", "1500")
    shortage = stock_doc(keeper, "adjustment", inv.wh_a, [{"item_id": it["id"], "qty": "-5"}], D3)
    assert balance(app, it["id"], inv.wh_a) == ("15.000", "22500.0000", "1500")
    v1 = keeper.get(f"/api/v1/accounting/vouchers/{surplus['voucher_id']}").get_json()
    assert {(ln["account_code"], ln["debit"], ln["credit"]) for ln in v1["lines"]} == {
        ("1301", "20000.0000", "0.0000"),
        ("5203", "0.0000", "20000.0000"),
    }
    v2 = keeper.get(f"/api/v1/accounting/vouchers/{shortage['voucher_id']}").get_json()
    assert {(ln["account_code"], ln["debit"], ln["credit"]) for ln in v2["lines"]} == {
        ("7108", "7500.0000", "0.0000"),
        ("1301", "0.0000", "7500.0000"),
    }
    kardex = keeper.get(
        f"/api/v1/inventory/kardex?item_id={it['id']}&warehouse_id={inv.wh_a}"
    ).get_json()
    assert [r["balance_qty"] for r in kardex["items"]] == ["10.000", "20.000", "15.000"]
    # Inventory GL equals stock value.
    fy = keeper.get("/api/v1/accounting/fiscal-years").get_json()[0]["id"]
    tb = keeper.get(f"/api/v1/accounting/reports/trial-balance?fiscal_year_id={fy}").get_json()
    inv_row = next(r for r in tb["rows"] if r["code"] == "1301")
    assert inv_row["balance_debit"] == "22500.0000"


def test_last_units_take_remaining_value(app: Flask, keeper: Api, inv: Inv) -> None:
    it = make_item(keeper, inv, "3001")
    stock_doc(
        keeper,
        "opening",
        inv.wh_a,
        [{"item_id": it["id"], "qty": "3", "unit_cost": "333.3333"}],
        D1,
    )
    stock_doc(keeper, "adjustment", inv.wh_a, [{"item_id": it["id"], "qty": "-1"}], D2)
    stock_doc(keeper, "adjustment", inv.wh_a, [{"item_id": it["id"], "qty": "-2"}], D3)
    qty, value, _ = balance(app, it["id"], inv.wh_a)
    assert (qty, value) == ("0.000", "0.0000")


def test_insufficient_stock_and_dates(keeper: Api, inv: Inv) -> None:
    it = make_item(keeper, inv, "4001")
    stock_doc(
        keeper, "opening", inv.wh_a, [{"item_id": it["id"], "qty": "5", "unit_cost": "100"}], D2
    )
    too_much = stock_doc(keeper, "adjustment", inv.wh_a, [{"item_id": it["id"], "qty": "-6"}], D3)
    assert too_much["error"]["code"] == "insufficient_stock"
    back = stock_doc(keeper, "adjustment", inv.wh_a, [{"item_id": it["id"], "qty": "-1"}], D1)
    assert back["error"]["code"] == "backdated_stock"
    future = keeper.post(
        "/api/v1/inventory/stock-documents",
        {
            "doc_type": "adjustment",
            "warehouse_id": inv.wh_a,
            "document_date": "2030-01-01",
            "lines": [{"item_id": it["id"], "qty": "-1"}],
        },
        idem=new_key(),
    )
    assert future.get_json()["error"]["code"] == "future_date"
    fraction = keeper.post(
        "/api/v1/inventory/stock-documents",
        {
            "doc_type": "adjustment",
            "warehouse_id": inv.wh_a,
            "document_date": D3.isoformat(),
            "lines": [{"item_id": it["id"], "qty": "-0.5"}],
        },
        idem=new_key(),
    )
    assert fraction.get_json()["error"]["code"] == "invalid_qty"


def test_transfer_moves_exact_value_without_voucher(app: Flask, keeper: Api, inv: Inv) -> None:
    it = make_item(keeper, inv, "5001")
    stock_doc(
        keeper,
        "opening",
        inv.wh_a,
        [{"item_id": it["id"], "qty": "3", "unit_cost": "333.3333"}],
        D1,
    )
    t = stock_doc(
        keeper, "transfer", inv.wh_a, [{"item_id": it["id"], "qty": "1"}], D2, dest=inv.wh_b
    )
    assert t["_status"] == 200 and t["voucher_id"] is None
    _, va, _ = balance(app, it["id"], inv.wh_a)
    _, vb, _ = balance(app, it["id"], inv.wh_b)
    assert va == "666.6666" and vb == "333.3333"
    same = keeper.post(
        "/api/v1/inventory/stock-documents",
        {
            "doc_type": "transfer",
            "warehouse_id": inv.wh_a,
            "dest_warehouse_id": inv.wh_a,
            "document_date": D3.isoformat(),
            "lines": [{"item_id": it["id"], "qty": "1"}],
        },
        idem=new_key(),
    )
    assert same.get_json()["error"]["code"] == "dest_required"


def test_count_creates_adjustment(app: Flask, keeper: Api, inv: Inv) -> None:
    a = make_item(keeper, inv, "6001")
    b = make_item(keeper, inv, "6002")
    stock_doc(
        keeper,
        "opening",
        inv.wh_a,
        [
            {"item_id": a["id"], "qty": "15", "unit_cost": "100"},
            {"item_id": b["id"], "qty": "4", "unit_cost": "50"},
        ],
        D1,
    )
    count = stock_doc(
        keeper,
        "count",
        inv.wh_a,
        [{"item_id": a["id"], "qty": "12"}, {"item_id": b["id"], "qty": "4"}],
        D2,
    )
    assert count["_status"] == 200
    assert [ln["system_qty"] for ln in count["lines"]] == ["15.000", "4.000"]
    docs = keeper.get("/api/v1/inventory/stock-documents?doc_type=adjustment").get_json()["items"]
    assert len(docs) == 1
    adj = keeper.get(f"/api/v1/inventory/stock-documents/{docs[0]['id']}").get_json()
    assert adj["source_document_id"] == count["id"] and adj["status"] == "final"
    assert [(ln["item_code"], ln["qty"]) for ln in adj["lines"]] == [("6001", "-3.000")]
    assert balance(app, a["id"], inv.wh_a)[0] == "12.000"


def test_concurrent_issues_cannot_oversell(app: Flask, keeper: Api, inv: Inv) -> None:
    it = make_item(keeper, inv, "7001")
    stock_doc(
        keeper, "opening", inv.wh_a, [{"item_id": it["id"], "qty": "8", "unit_cost": "10"}], D1
    )
    drafts = [
        stock_doc(
            keeper, "adjustment", inv.wh_a, [{"item_id": it["id"], "qty": "-5"}], D2, finalize=False
        )
        for _ in range(2)
    ]
    results: list[int] = []
    clients = []
    for _ in drafts:
        c = Api(app.test_client())
        assert c.login("keeper").status_code == 200
        clients.append(c)

    def go(c: Api, d: dict) -> None:
        r = c.post(
            f"/api/v1/inventory/stock-documents/{d['id']}/finalize",
            headers={"If-Match": d["row_version"]},
        )
        results.append(r.status_code)

    threads = [
        threading.Thread(target=go, args=(c, d)) for c, d in zip(clients, drafts, strict=True)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 422]
    assert balance(app, it["id"], inv.wh_a)[0] == "3.000"


def test_kardex_is_append_only(app: Flask, keeper: Api, inv: Inv) -> None:
    it = make_item(keeper, inv, "8001")
    stock_doc(
        keeper, "opening", inv.wh_a, [{"item_id": it["id"], "qty": "1", "unit_cost": "1"}], D1
    )
    with app.app_context():
        s = new_session()
        try:
            with pytest.raises(DBAPIError, match="append-only"):
                s.execute(text("UPDATE stock_ledger SET qty_in = 100"))
        finally:
            s.rollback()
            s.close()


def test_permissions(app: Flask, inv: Inv, seed: Seed) -> None:
    make_user(app, "wh_only", ["WHK"])
    w = Api(app.test_client())
    w.login("wh_only")
    priced = w.post(
        "/api/v1/inventory/items",
        {"code": "P1", "name": "کالا", "base_unit_id": inv.pcs, "prices": [{"price": "1"}]},
        idem=new_key(),
    )
    assert priced.status_code == 403
    make_user(app, "cashier", ["CSH"])
    c = Api(app.test_client())
    c.login("cashier")
    doc = c.post(
        "/api/v1/inventory/stock-documents",
        {
            "doc_type": "opening",
            "warehouse_id": inv.wh_a,
            "document_date": D1.isoformat(),
            "lines": [{"item_id": str(uuid.uuid4()), "qty": "1", "unit_cost": "1"}],
        },
        idem=new_key(),
    )
    assert doc.status_code == 403


# --- Excel import -------------------------------------------------------------


def xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["header"] * 11)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(api: Api, path: str, content: bytes, form: dict | None = None, key: str | None = None):
    data = {"file": (io.BytesIO(content), "items.xlsx"), **(form or {})}
    headers = {"X-CSRF-Token": api.c.get_cookie("nextcam_csrf").value}  # type: ignore[union-attr]
    if key:
        headers["Idempotency-Key"] = key
    return api.c.post(path, data=data, headers=headers, content_type="multipart/form-data")


def test_excel_import_items_and_opening(app: Flask, keeper: Api, inv: Inv) -> None:
    template = keeper.get("/api/v1/inventory/import/items/template")
    assert template.status_code == 200 and template.data[:2] == b"PK"
    bad = xlsx(
        [
            [
                "1001",
                "شیر پرچرب",
                "لبنیات",
                "عدد",
                "6260100212345",
                "42000",
                "خیر",
                "",
                "بله",
                "",
                "24",
            ],
            ["1002", "ماست", "لبنیات", "واحد ناموجود", "", "abc", "شاید", "", "خیر", "", ""],
            ["1001", "تکراری", "", "عدد", "6260100212345", "", "خیر", "", "خیر", "", ""],
        ]
    )
    preview = upload(keeper, "/api/v1/inventory/import/items/preview", bad).get_json()
    assert preview["valid_rows"] == 1
    assert {(e["row"], e["column"]) for e in preview["errors"]} >= {
        (3, "واحد"),
        (3, "قیمت فروش"),
        (3, "وزنی"),
        (4, "کد کالا"),
    }
    refused = upload(keeper, "/api/v1/inventory/import/items/commit", bad, key=new_key())
    assert refused.get_json()["error"]["code"] == "import_has_errors"

    good = xlsx(
        [
            [
                "1001",
                "شیر پرچرب ۱ لیتری",
                "لبنیات",
                "عدد",
                "6260100212345, 6260100212346",
                "42000",
                "خیر",
                "",
                "بله",
                "",
                "24",
            ],
            [
                "1002",
                "گوشت گوسفندی",
                "پروتئین",
                "کیلوگرم",
                "",
                "890000",
                "بله",
                "123",
                "خیر",
                "",
                "",
            ],
        ]
    )
    done = upload(keeper, "/api/v1/inventory/import/items/commit", good, key=new_key())
    assert done.status_code == 201, done.get_json()
    assert done.get_json() == {"created": 2, "updated": 0, "document_id": None}
    milk = keeper.get("/api/v1/inventory/items/lookup?barcode=6260100212346").get_json()
    assert milk["unit_price"] == "420000.0000"  # toman ×10

    again = xlsx(
        [["1001", "شیر پرچرب ۱ لیتری", "لبنیات", "عدد", "", "45000", "خیر", "", "بله", "", ""]]
    )
    upd = upload(keeper, "/api/v1/inventory/import/items/commit", again, key=new_key()).get_json()
    assert upd["updated"] == 1
    assert (
        keeper.get("/api/v1/inventory/items/lookup?barcode=6260100212345").get_json()["unit_price"]
        == "450000.0000"
    )

    opening = xlsx([["1001", "100", "30000", ""], ["6260100212345", "1", "1", ""]])
    pv = upload(keeper, "/api/v1/inventory/import/opening/preview", opening).get_json()
    assert pv["valid_rows"] == 1 and pv["errors"][0]["row"] == 3
    ok = upload(
        keeper,
        "/api/v1/inventory/import/opening/commit",
        xlsx([["1001", "100", "30000", ""], ["1002", "12.5", "650000", ""]]),
        form={"warehouse_id": inv.wh_a, "document_date": D1.isoformat()},
        key=new_key(),
    )
    assert ok.status_code == 201, ok.get_json()
    doc = keeper.get(f"/api/v1/inventory/stock-documents/{ok.get_json()['document_id']}").get_json()
    assert doc["status"] == "draft" and len(doc["lines"]) == 2
    assert doc["lines"][1]["unit_cost"] == "6500000.000000"


# --- performance (run explicitly: pytest -m perf) -----------------------------


@pytest.mark.perf
def test_lookup_latency_with_50k_items(app: Flask, keeper: Api, inv: Inv) -> None:
    import time

    with app.app_context():
        s = new_session()
        s.execute(
            text(
                f"""
            WITH n AS (SELECT TOP 50000 ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
                       FROM sys.all_objects a CROSS JOIN sys.all_objects b)
            INSERT INTO item (id, code, name, base_unit_id, item_type, is_weighted, track_expiry,
                              vat_exempt, is_active, created_at, updated_at)
            SELECT NEWID(), CONCAT('P', i), CONCAT(N'کالای آزمایشی ', i), '{inv.pcs}',
                   'goods', 0, 0, 0, 1, SYSUTCDATETIME(), SYSUTCDATETIME() FROM n;
            INSERT INTO item_barcode (id, barcode, item_id, created_at, updated_at)
            SELECT NEWID(),
                   CONCAT('62601', RIGHT(CONCAT('00000000', SUBSTRING(code, 2, 10)), 8)),
                   id, SYSUTCDATETIME(), SYSUTCDATETIME() FROM item WHERE code LIKE 'P%';
            """
            )
        )
        s.commit()
        s.close()
    timings = []
    for i in range(1, 501):
        bc = f"62601{(i * 97) % 50000 + 1:08d}"
        t0 = time.perf_counter()
        r = keeper.get(f"/api/v1/inventory/items/lookup?barcode={bc}")
        timings.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200
    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    print(f"\nlookup over 50k items: p50={timings[len(timings) // 2]:.1f}ms p95={p95:.1f}ms")
    assert p95 < 100


@pytest.mark.perf
def test_import_20k_items(keeper: Api, inv: Inv) -> None:
    import time

    rows = [
        [
            f"K{i}",
            f"کالای وارداتی {i}",
            f"گروه {i % 40}",
            "عدد",
            f"62609{i:08d}",
            str(1000 + i),
            "خیر",
            "",
            "خیر",
            "",
            "",
        ]
        for i in range(1, 20001)
    ]
    content = xlsx(rows)
    t0 = time.perf_counter()
    preview = upload(keeper, "/api/v1/inventory/import/items/preview", content).get_json()
    t1 = time.perf_counter()
    done = upload(keeper, "/api/v1/inventory/import/items/commit", content, key=new_key())
    t2 = time.perf_counter()
    assert preview["valid_rows"] == 20000 and done.status_code == 201, done.get_json()
    print(
        f"\nimport 20k items: preview={t1 - t0:.1f}s commit={t2 - t1:.1f}s "
        f"file={len(content) / 1024:.0f}KB"
    )
