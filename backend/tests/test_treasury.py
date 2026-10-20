"""Treasury: money accounts, receipts/payments/transfers/settlements and their vouchers,
cheque lifecycle, reversal, bank statement import, matching and reconciliation."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import jdatetime
import pytest
from flask import Flask
from openpyxl import Workbook
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import new_session, unit_of_work
from app.modules.accounting.models import Account, VoucherLine
from app.modules.accounting.services.chart import seed_defaults
from app.modules.accounting.services.fiscal import ensure_year
from tests.conftest import Api, Seed, make_user, new_key

pytestmark = pytest.mark.db

D = date(2026, 5, 1)


@dataclass
class Tr:
    api: Api
    branch: str
    customer: str
    supplier: str
    cash: str
    bank: str


def login(app: Flask, username: str) -> Api:
    a = Api(app.test_client())
    assert a.login(username).status_code == 200
    return a


def valid_iban(bban: str) -> str:
    """IR + check digits for a 22-digit BBAN (ISO 13616 mod 97)."""
    check = 98 - int(bban + "182700") % 97
    return f"IR{check:02d}{bban}"


@pytest.fixture
def tr(app: Flask, seed: Seed) -> Tr:
    with app.app_context(), unit_of_work() as s:
        seed_defaults(s)
        ensure_year(s, 1405)
    make_user(app, "treas", ["ACC"])
    api = login(app, "treas")

    def post(path: str, body: dict) -> str:
        r = api.post(path, body, idem=new_key())
        assert r.status_code == 201, r.get_json()
        return r.get_json()["id"]

    return Tr(
        api=api,
        branch=str(seed.branch_a),
        customer=post("/api/v1/parties", {"code": "C1", "name": "رستوران آفتاب"}),
        supplier=post(
            "/api/v1/parties",
            {"code": "S1", "name": "پخش البرز", "is_customer": False, "is_supplier": True},
        ),
        cash=post(
            "/api/v1/treasury/accounts",
            {
                "code": "CASH-01",
                "name": "صندوق مرکزی",
                "kind": "cash",
                "branch_id": str(seed.branch_a),
            },
        ),
        bank=post(
            "/api/v1/treasury/accounts",
            {
                "code": "BANK-01",
                "name": "بانک ملت جاری",
                "kind": "bank",
                "bank_name": "ملت",
                "iban": valid_iban("0120000000001234567890"),
            },
        ),
    )


def voucher(app: Flask, voucher_id: str) -> list[tuple[str, str, str]]:
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


def balances(t: Tr) -> dict[str, str]:
    return {a["code"]: a["balance"] for a in t.api.get("/api/v1/treasury/accounts").get_json()}


def receipt(t: Tr, lines: list[dict], when: date = D, kind: str = "receipts", **kw: object):
    body = {
        "branch_id": t.branch,
        "document_date": when.isoformat(),
        "party_id": t.customer if kind == "receipts" else t.supplier,
        "lines": lines,
        **kw,
    }
    return t.api.post(f"/api/v1/treasury/{kind}", body, idem=new_key())


def cheque(number: str, due: date) -> dict:
    return {"number": number, "bank_name": "صادرات", "due_date": due.isoformat()}


def act(t: Tr, cheque_id: str, action: str, when: date = D, **kw: object):
    c = t.api.get(f"/api/v1/treasury/cheques/{cheque_id}").get_json()
    return t.api.post(
        f"/api/v1/treasury/cheques/{cheque_id}/actions",
        {"action": action, "event_date": when.isoformat(), **kw},
        headers={"If-Match": c["row_version"]},
    )


def test_accounts_and_documents_post_vouchers(app: Flask, tr: Tr) -> None:
    bad = tr.api.post(
        "/api/v1/treasury/accounts",
        {"code": "B2", "name": "بانک", "kind": "bank", "iban": "IR000120000000001234567890"},
        idem=new_key(),
    )
    assert bad.status_code == 400 and "شبا" in str(bad.get_json())
    no_branch = tr.api.post(
        "/api/v1/treasury/accounts", {"code": "C2", "name": "صندوق", "kind": "cash"}, idem=new_key()
    )
    assert no_branch.status_code == 400

    r = receipt(
        tr,
        [
            {"method": "cash", "money_account_id": tr.cash, "amount": "3000000"},
            {"method": "bank", "money_account_id": tr.bank, "amount": "2000000", "reference": "R1"},
            {
                "method": "cheque",
                "amount": "5000000",
                "cheque": cheque("100001", D + timedelta(30)),
            },
        ],
    )
    assert r.status_code == 201, r.get_json()
    rec = r.get_json()
    assert (rec["status"], rec["number"], rec["amount"], rec["against"]) == (
        "final",
        1,
        "10000000.0000",
        "receivable",
    )
    assert rec["lines"][2]["cheque_status"] == "in_hand"
    assert voucher(app, rec["voucher_id"]) == [
        ("1101", "3000000", "0"),
        ("1103", "2000000", "0"),
        ("1201", "0", "10000000"),
        ("1202", "5000000", "0"),
    ]
    assert balances(tr) == {"CASH-01": "3000000.0000", "BANK-01": "2000000.0000"}

    p = receipt(
        tr,
        [
            {"method": "cash", "money_account_id": tr.cash, "amount": "1000000"},
            {
                "method": "cheque",
                "money_account_id": tr.bank,
                "amount": "4000000",
                "cheque": cheque("900001", D + timedelta(10)),
            },
        ],
        kind="payments",
    )
    assert p.status_code == 201, p.get_json()
    pay = p.get_json()
    assert pay["against"] == "payable" and pay["lines"][1]["cheque_status"] == "issued"
    assert voucher(app, pay["voucher_id"]) == [
        ("1101", "0", "1000000"),
        ("3101", "5000000", "0"),
        ("3102", "0", "4000000"),
    ]
    # Cash never goes negative.
    over = receipt(
        tr, [{"method": "cash", "money_account_id": tr.cash, "amount": "2500000"}], kind="payments"
    )
    assert over.get_json()["error"]["code"] == "insufficient_cash"
    # An issued cheque needs the bank account it is drawn on.
    no_bank = receipt(
        tr,
        [{"method": "cheque", "amount": "1", "cheque": cheque("900002", D)}],
        kind="payments",
    )
    assert no_bank.get_json()["error"]["code"] == "cheque_account_required"

    t = tr.api.post(
        "/api/v1/treasury/transfers",
        {
            "branch_id": tr.branch,
            "document_date": D.isoformat(),
            "from_account_id": tr.cash,
            "to_account_id": tr.bank,
            "amount": "1500000",
        },
        idem=new_key(),
    )
    assert t.status_code == 201, t.get_json()
    assert voucher(app, t.get_json()["voucher_id"]) == [
        ("1101", "0", "1500000"),
        ("1103", "1500000", "0"),
    ]
    st = tr.api.post(
        "/api/v1/treasury/settlements",
        {
            "branch_id": tr.branch,
            "document_date": D.isoformat(),
            "bank_account_id": tr.bank,
            "amount": "10000000",
            "fee": "50000",
        },
        idem=new_key(),
    )
    assert st.status_code == 201, st.get_json()
    assert voucher(app, st.get_json()["voucher_id"]) == [
        ("1103", "9950000", "0"),
        ("1104", "0", "10000000"),
        ("7105", "50000", "0"),
    ]
    assert balances(tr) == {"CASH-01": "500000.0000", "BANK-01": "13450000.0000"}
    listed = tr.api.get("/api/v1/treasury/documents?kind=receipt").get_json()
    assert [d["party_name"] for d in listed["items"]] == ["رستوران آفتاب"]

    make_user(app, "cash", ["CSH"])
    assert login(app, "cash").get("/api/v1/treasury/accounts").status_code == 403


def test_cheque_lifecycle(app: Flask, tr: Tr) -> None:
    rec = receipt(
        tr,
        [
            {"method": "cheque", "amount": "5000000", "cheque": cheque("1", D + timedelta(5))},
            {"method": "cheque", "amount": "3000000", "cheque": cheque("2", D + timedelta(60))},
        ],
    ).get_json()
    good, bad = (ln["cheque_id"] for ln in rec["lines"])

    dep = act(tr, good, "deposit", money_account_id=tr.bank)
    assert dep.status_code == 200, dep.get_json()
    assert dep.get_json()["status"] == "deposited" and dep.get_json()["actions"] == [
        "clear",
        "bounce",
    ]
    assert dep.get_json()["events"][-1]["voucher_id"] is None  # no money moved yet
    clear = act(tr, good, "clear", D + timedelta(6)).get_json()
    assert (clear["status"], clear["actions"], len(clear["events"])) == ("cleared", [], 3)
    assert voucher(app, clear["events"][-1]["voucher_id"]) == [
        ("1103", "5000000", "0"),
        ("1202", "0", "5000000"),
    ]
    assert act(tr, good, "bounce").get_json()["error"]["code"] == "bad_cheque_action"
    assert act(tr, bad, "deposit").get_json()["error"]["code"] == "account_required"

    act(tr, bad, "deposit", money_account_id=tr.bank)
    bounced = act(tr, bad, "bounce", D + timedelta(61)).get_json()
    assert voucher(app, bounced["events"][-1]["voucher_id"]) == [
        ("1201", "3000000", "0"),
        ("1202", "0", "3000000"),
    ]
    back = act(tr, bad, "return", D + timedelta(62)).get_json()
    assert back["status"] == "returned" and back["events"][-1]["voucher_id"] is None
    # The customer owes the bounced amount again; the cleared one is settled.
    party = tr.api.get(f"/api/v1/parties/{tr.customer}").get_json()
    assert party["balance"] == "-5000000.0000"

    pay = receipt(
        tr,
        [
            {
                "method": "cheque",
                "money_account_id": tr.bank,
                "amount": "1000000",
                "cheque": cheque("901", D + timedelta(3)),
            },
            {
                "method": "cheque",
                "money_account_id": tr.bank,
                "amount": "700000",
                "cheque": cheque("902", D + timedelta(90)),
            },
        ],
        kind="payments",
    ).get_json()
    paid, cancelled = (ln["cheque_id"] for ln in pay["lines"])
    due = tr.api.get(
        f"/api/v1/treasury/cheques?direction=issued&due_until={(D + timedelta(30)).isoformat()}"
    ).get_json()
    assert [c["number"] for c in due["items"]] == ["901"]
    cl = act(tr, paid, "clear", D + timedelta(3)).get_json()
    assert voucher(app, cl["events"][-1]["voucher_id"]) == [
        ("1103", "0", "1000000"),
        ("3102", "1000000", "0"),
    ]
    cn = act(tr, cancelled, "cancel", D + timedelta(4)).get_json()
    assert voucher(app, cn["events"][-1]["voucher_id"]) == [
        ("3101", "0", "700000"),
        ("3102", "700000", "0"),
    ]
    assert act(tr, paid, "clear", D - timedelta(1)).get_json()["error"]["code"] in (
        "bad_cheque_action",
        "bad_dates",
    )
    # History is append-only and a cheque's identity never changes.
    with app.app_context(), pytest.raises(DBAPIError), unit_of_work() as s:
        s.execute(text("UPDATE cheque_event SET note = N'x' WHERE cheque_id = :id"), {"id": paid})
    with app.app_context(), pytest.raises(DBAPIError), unit_of_work() as s:
        s.execute(text("UPDATE cheque SET amount = 1 WHERE id = :id"), {"id": paid})


def test_reversal(app: Flask, tr: Tr) -> None:
    rec = receipt(
        tr,
        [
            {"method": "cash", "money_account_id": tr.cash, "amount": "2000000"},
            {"method": "cheque", "amount": "1000000", "cheque": cheque("7", D + timedelta(9))},
        ],
    ).get_json()
    path = f"/api/v1/treasury/documents/{rec['id']}/reverse"
    r = tr.api.post(path, {"reason": "ثبت اشتباه"}, headers={"If-Match": rec["row_version"]})
    assert r.status_code == 200, r.get_json()
    rev = r.get_json()
    assert rev["status"] == "reversed" and rev["reversal_voucher_id"]
    assert rev["lines"][1]["cheque_status"] == "void"
    assert voucher(app, rev["reversal_voucher_id"]) == [
        ("1101", "0", "2000000"),
        ("1201", "3000000", "0"),
        ("1202", "0", "1000000"),
    ]
    assert balances(tr)["CASH-01"] == "0.0000"
    assert tr.api.get(f"/api/v1/parties/{tr.customer}").get_json()["balance"] == "0.0000"
    again = tr.api.post(path, {"reason": "دوباره"}, headers={"If-Match": rev["row_version"]})
    assert again.get_json()["error"]["code"] == "already_reversed"

    moved = receipt(
        tr, [{"method": "cheque", "amount": "500000", "cheque": cheque("8", D)}]
    ).get_json()
    act(tr, moved["lines"][0]["cheque_id"], "deposit", money_account_id=tr.bank)
    moved = tr.api.get(f"/api/v1/treasury/documents/{moved['id']}").get_json()
    r = tr.api.post(
        f"/api/v1/treasury/documents/{moved['id']}/reverse",
        {"reason": "x1"},
        headers={"If-Match": moved["row_version"]},
    )
    assert r.get_json()["error"]["code"] == "cheque_moved"

    spent = receipt(tr, [{"method": "cash", "money_account_id": tr.cash, "amount": "800000"}])
    spent = spent.get_json()
    receipt(
        tr, [{"method": "cash", "money_account_id": tr.cash, "amount": "500000"}], kind="payments"
    )
    r = tr.api.post(
        f"/api/v1/treasury/documents/{spent['id']}/reverse",
        {"reason": "x2"},
        headers={"If-Match": spent["row_version"]},
    )
    assert r.get_json()["error"]["code"] == "insufficient_cash"

    with app.app_context(), pytest.raises(DBAPIError), unit_of_work() as s:
        s.execute(
            text("UPDATE treasury_document SET amount = 1 WHERE id = :id"), {"id": spent["id"]}
        )
    with app.app_context(), pytest.raises(DBAPIError), unit_of_work() as s:
        s.execute(text("DELETE FROM treasury_line WHERE document_id = :id"), {"id": spent["id"]})


def statement_xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["h"] * 6)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(api: Api, path: str, content: bytes, key: str | None = None):
    headers = {"X-CSRF-Token": api.c.get_cookie("nextcam_csrf").value}  # type: ignore[union-attr]
    if key:
        headers["Idempotency-Key"] = key
    return api.c.post(
        path,
        data={"file": (io.BytesIO(content), "statement.xlsx")},
        headers=headers,
        content_type="multipart/form-data",
    )


def jalali(d: date) -> str:
    return jdatetime.date.fromgregorian(date=d).strftime("%Y/%m/%d")


def test_bank_statement_matching_and_reconciliation(app: Flask, tr: Tr) -> None:
    receipt(
        tr,
        [{"method": "bank", "money_account_id": tr.bank, "amount": "2000000", "reference": "R1"}],
    )
    receipt(
        tr,
        [{"method": "bank", "money_account_id": tr.bank, "amount": "700000"}],
        when=D + timedelta(1),
        kind="payments",
    )
    tr.api.post(
        "/api/v1/treasury/settlements",
        {
            "branch_id": tr.branch,
            "document_date": (D + timedelta(2)).isoformat(),
            "bank_account_id": tr.bank,
            "amount": "10000000",
            "fee": "50000",
        },
        idem=new_key(),
    )
    base = f"/api/v1/treasury/accounts/{tr.bank}/statement"
    broken = statement_xlsx(
        [["1405/13/40", "x", "", "1", "", ""], [jalali(D), "y", "", "1", "1", ""]]
    )
    pv = upload(tr.api, f"{base}/preview", broken).get_json()
    assert {(e["row"], e["column"]) for e in pv["errors"]} == {(2, "تاریخ *"), (3, "واریز (ریال)")}

    good = statement_xlsx(
        [
            [jalali(D), "واریز", "R1", "2,000,000", "", "2000000"],
            [datetime(2026, 5, 2), "برداشت", "", "", 700000, 1300000],
            [jalali(D + timedelta(3)), "کارمزد", "", "", "12000", "1288000"],
        ]
    )
    pv = upload(tr.api, f"{base}/preview", good).get_json()
    assert (pv["new_rows"], pv["duplicate_rows"], pv["errors"]) == (3, 0, [])
    done = upload(tr.api, f"{base}/commit", good, new_key())
    assert done.status_code == 201, done.get_json()
    again = upload(tr.api, f"{base}/commit", good, new_key()).get_json()
    assert (again["new_rows"], again["duplicate_rows"]) == (0, 3)

    auto = tr.api.post(f"{base}/auto-match").get_json()
    assert auto == {"matched": 2, "ambiguous": 0, "unmatched": 1}
    rec = tr.api.get(
        f"/api/v1/treasury/accounts/{tr.bank}/reconciliation?as_of={(D + timedelta(5)).isoformat()}"
    ).get_json()
    assert (rec["book_balance"], rec["statement_balance"], rec["adjusted_book_balance"]) == (
        "11250000.0000",
        "1288000.0000",
        "1288000.0000",
    )
    assert [b["amount"] for b in rec["book_unmatched"]] == ["9950000.0000"]
    assert [ln["amount"] for ln in rec["statement_unmatched"]] == ["-12000.0000"]

    lines = tr.api.get(f"{base}?matched=true").get_json()["items"]
    first = lines[0]
    assert first["voucher_number"] is not None
    un = tr.api.post(f"/api/v1/treasury/statement-lines/{first['id']}/unmatch")
    assert un.status_code == 200 and un.get_json()["voucher_line_id"] is None
    cands = tr.api.get(f"/api/v1/treasury/statement-lines/{first['id']}/candidates").get_json()
    assert len(cands) == 1 and cands[0]["amount"] == "2000000.0000"
    m = tr.api.post(
        f"/api/v1/treasury/statement-lines/{first['id']}/match",
        {"voucher_line_id": cands[0]["voucher_line_id"]},
    )
    assert m.status_code == 200, m.get_json()
    fee = tr.api.get(f"{base}?matched=false").get_json()["items"][0]
    assert tr.api.get(f"/api/v1/treasury/statement-lines/{fee['id']}/candidates").get_json() == []
    wrong = tr.api.post(
        f"/api/v1/treasury/statement-lines/{fee['id']}/match",
        {"voucher_line_id": cands[0]["voucher_line_id"]},
    )
    assert wrong.get_json()["error"]["code"] == "amount_mismatch"
