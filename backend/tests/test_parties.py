"""Counterparties: identity validation, masking, balances, statement, notes, Excel import."""

from __future__ import annotations

import io
from datetime import date

import pytest
from flask import Flask
from openpyxl import Workbook

from app.core.db import unit_of_work
from app.modules.accounting.services.chart import seed_defaults
from app.modules.accounting.services.fiscal import ensure_year
from tests.conftest import Api, Seed, make_user, new_key

pytestmark = pytest.mark.db

VALID_CODE = "0012345679"  # passes the national-code checksum
D = date(2026, 5, 1)


def login(app: Flask, username: str) -> Api:
    a = Api(app.test_client())
    assert a.login(username).status_code == 200
    return a


@pytest.fixture
def acc(app: Flask, seed: Seed) -> Api:
    with app.app_context(), unit_of_work() as s:
        seed_defaults(s)
        ensure_year(s, 1405)
    make_user(app, "acc", ["ACC"])
    return login(app, "acc")


def create(api: Api, code: str, **kw: object):
    body = {"code": code, "name": f"طرف {code}", **kw}
    return api.post("/api/v1/parties", body, idem=new_key())


def test_identity_validation_and_uniqueness(acc: Api) -> None:
    ok = create(
        acc, "P1", national_id="۰۰۱۲۳۴۵۶۷۹", mobile="+989121234567", postal_code="1234567890"
    )
    assert ok.status_code == 201, ok.get_json()
    p = ok.get_json()
    assert (p["national_id"], p["mobile"], p["masked"]) == (VALID_CODE, "09121234567", False)
    bad = create(acc, "P2", national_id="0012345678")
    assert bad.status_code == 400 and "کد ملی" in str(bad.get_json())
    company = create(
        acc,
        "P3",
        party_type="company",
        national_id="10101010101",
        is_customer=False,
        is_supplier=True,
    )
    assert company.status_code == 201
    dup = create(acc, "P4", national_id=VALID_CODE)
    assert dup.get_json()["error"]["code"] == "national_id_taken"
    no_role = create(acc, "P5", is_customer=False, is_supplier=False)
    assert no_role.status_code == 400
    assert create(acc, "P1").get_json()["error"]["code"] == "party_code_taken"


def test_sensitive_fields_masked_without_manage(app: Flask, acc: Api) -> None:
    p = create(
        acc, "P1", national_id=VALID_CODE, mobile="09121234567", address="تهران، خیابان آزادی"
    ).get_json()
    make_user(app, "auditor", ["AUD"])
    aud = login(app, "auditor")
    seen = aud.get(f"/api/v1/parties/{p['id']}").get_json()
    assert seen["masked"] is True
    assert seen["national_id"] == "00••••••79" and seen["mobile"] == "09•••••••67"
    assert "آزادی" not in (seen["address"] or "")
    listed = aud.get("/api/v1/parties").get_json()["items"][0]
    assert listed["mobile"] == "09•••••••67"
    assert (
        aud.post("/api/v1/parties", {"code": "X1", "name": "xx"}, idem=new_key()).status_code == 403
    )
    make_user(app, "cash", ["CSH"])
    assert login(app, "cash").get("/api/v1/parties").status_code == 403


def test_update_with_version_and_credit_limit(acc: Api) -> None:
    p = create(acc, "P1", credit_limit="5000000").get_json()
    body = {"name": "نام تازه", "is_customer": True, "credit_limit": "7000000", "is_active": True}
    stale = acc.put(f"/api/v1/parties/{p['id']}", body, "AAAAAAAAAAA=")
    assert stale.status_code == 409
    upd = acc.put(f"/api/v1/parties/{p['id']}", body, p["row_version"])
    assert upd.status_code == 200, upd.get_json()
    assert (upd.get_json()["name"], upd.get_json()["credit_limit"]) == ("نام تازه", "7000000.0000")
    # A supplier-only party never carries a credit limit and is not offered for credit sales.
    sup = create(acc, "S1", is_customer=False, is_supplier=True, credit_limit="100").get_json()
    assert sup["credit_limit"] is None


def test_unlimited_credit(acc: Api) -> None:
    p = create(acc, "U1", credit_unlimited=True).get_json()
    assert (p["credit_unlimited"], p["credit_limit"]) == (True, None)
    both = create(acc, "U2", credit_unlimited=True, credit_limit="1000")
    assert both.status_code == 400
    # Back to a limit: the flag goes off in the same edit.
    body = {"name": p["name"], "is_customer": True, "credit_limit": "5000", "is_active": True}
    upd = acc.put(f"/api/v1/parties/{p['id']}", body, p["row_version"]).get_json()
    assert (upd["credit_unlimited"], upd["credit_limit"]) == (False, "5000.0000")
    # A supplier-only party never gets credit.
    sup = create(acc, "S2", is_customer=False, is_supplier=True, credit_unlimited=True).get_json()
    assert sup["credit_unlimited"] is False


def xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["h"] * 14)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(api: Api, path: str, content: bytes, form: dict | None = None, key: str | None = None):
    data = {"file": (io.BytesIO(content), "parties.xlsx"), **(form or {})}
    headers = {"X-CSRF-Token": api.c.get_cookie("nextcam_csrf").value}  # type: ignore[union-attr]
    if key:
        headers["Idempotency-Key"] = key
    return api.c.post(path, data=data, headers=headers, content_type="multipart/form-data")


def test_import_with_opening_balances_statement_and_notes(app: Flask, seed: Seed, acc: Api) -> None:
    make_user(app, "boss", ["MGR", "ADM"])
    boss = login(app, "boss")
    bad = xlsx(
        [
            ["C1", "رستوران آفتاب", "حقوقی", "بله", "خیر", "", "", "0912", "", "", "", "", "", ""],
            ["C2", "کافه", "", "", "", "", "", "", "", "", "", "", "100", "50"],
        ]
    )
    pv = upload(boss, "/api/v1/parties/import/preview", bad).get_json()
    assert {(e["row"], e["column"]) for e in pv["errors"]} == {
        (2, "موبایل"),
        (3, "مانده بدهکار (طلب ما)"),
    }
    assert (
        upload(boss, "/api/v1/parties/import/commit", bad, key=new_key()).get_json()["error"][
            "code"
        ]
        == "import_has_errors"
    )

    good = xlsx(
        [
            [
                "C1",
                "رستوران آفتاب",
                "حقوقی",
                "بله",
                "خیر",
                "",
                "",
                "09120000000",
                "",
                "",
                "",
                "5000000",
                "1200000",
                "",
            ],
            ["S1", "پخش البرز", "حقوقی", "خیر", "بله", "", "", "", "", "", "", "", "", "3000000"],
            ["P1", "علی رضایی", "حقیقی", "", "", VALID_CODE, "", "", "", "", "", "", "", ""],
        ]
    )
    done = upload(
        boss, "/api/v1/parties/import/commit", good, {"opening_date": D.isoformat()}, key=new_key()
    )
    assert done.status_code == 201, done.get_json()
    res = done.get_json()
    assert (res["created"], res["updated"]) == (3, 0) and res["document_id"]
    # Opening balances wait as a draft voucher (toman → rial).
    v = acc.get(f"/api/v1/accounting/vouchers/{res['document_id']}").get_json()
    assert v["status"] == "draft" and v["total_debit"] == "42000000.0000"
    assert (
        acc.post(
            f"/api/v1/accounting/vouchers/{v['id']}/finalize",
            headers={"If-Match": v["row_version"]},
        ).status_code
        == 200
    )

    parties = {p["code"]: p for p in acc.get("/api/v1/parties?page_size=50").get_json()["items"]}
    assert (
        parties["C1"]["balance"] == "12000000.0000" and parties["S1"]["balance"] == "-30000000.0000"
    )
    assert [p["code"] for p in acc.get("/api/v1/parties?balance=debtor").get_json()["items"]] == [
        "C1"
    ]
    assert [p["code"] for p in acc.get("/api/v1/parties?role=supplier").get_json()["items"]] == [
        "S1"
    ]

    st = acc.get(f"/api/v1/parties/{parties['C1']['id']}/statement").get_json()
    assert (st["opening_balance"], st["closing_balance"], len(st["lines"])) == (
        "0.0000",
        "12000000.0000",
        1,
    )
    later = acc.get(
        f"/api/v1/parties/{parties['C1']['id']}/statement?date_from=2026-06-01"
    ).get_json()
    assert later["opening_balance"] == "12000000.0000" and later["lines"] == []

    # Re-import the same codes: details update, a second opening balance is refused.
    again = upload(boss, "/api/v1/parties/import/preview", good).get_json()
    refused = {e["row"] for e in again["errors"] if "مانده افتتاحیه" in e["message"]}
    assert refused == {2, 3} and again["to_update"] == 1  # P1 has no balance: plain update

    n = acc.post(
        f"/api/v1/parties/{parties['C1']['id']}/notes",
        {"body": "تماس برای تسویه", "follow_up_on": "2026-01-01"},
    )
    assert n.status_code == 201
    due = acc.get("/api/v1/parties/follow-ups").get_json()
    assert [x["body"] for x in due] == ["تماس برای تسویه"]
    acc.post(f"/api/v1/parties/notes/{n.get_json()['id']}/done", {"done": True})
    assert acc.get("/api/v1/parties/follow-ups").get_json() == []

    # Credit sales offer customers only.
    make_user(app, "sup", ["SUP"])
    names = [c["name"] for c in login(app, "sup").get("/api/v1/sales/customers").get_json()]
    assert "رستوران آفتاب" in names and "پخش البرز" not in names
