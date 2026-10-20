"""Accounting core: vouchers, numbering, immutability, reports, posting rules, year closing."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import new_session, unit_of_work
from app.core.errors import DomainError
from app.modules.accounting.models import Account, DetailAccount, PostingRule, Voucher
from app.modules.accounting.services.chart import seed_defaults
from app.modules.accounting.services.fiscal import ensure_year
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.accounting.services.vouchers import finalize_voucher
from tests.conftest import Api, Seed, make_user, new_key

pytestmark = pytest.mark.db

D = Decimal
IN_1405 = date(2026, 10, 11)  # 1405/07/19
MEHR_1405 = date(2026, 9, 23)  # 1405/07/01


@dataclass
class Books:
    fy: str
    acc: dict[str, str]
    customer: str
    bank: str
    branch: str


@pytest.fixture
def books(app: Flask, seed: Seed) -> Books:
    with app.app_context(), unit_of_work() as s:
        seed_defaults(s)
        fy = ensure_year(s, 1405)
        cust = DetailAccount(code="C001", name="مشتری نمونه", kind="person", is_active=True)
        bank = DetailAccount(code="B001", name="بانک ملت - جاری", kind="bank", is_active=True)
        s.add_all([cust, bank])
        s.flush()
        acc = {a.code: str(a.id) for a in s.scalars(select(Account))}
        return Books(str(fy.id), acc, str(cust.id), str(bank.id), str(seed.branch_a))


@pytest.fixture
def accountant(app: Flask, seed: Seed) -> Api:
    make_user(app, "accountant", ["ACC", "MGR"])
    a = Api(app.test_client())
    assert a.login("accountant").status_code == 200
    return a


def line(acc: str, debit: str = "0", credit: str = "0", detail: str | None = None) -> dict:
    out = {"account_id": acc, "debit": debit, "credit": credit}
    if detail:
        out["detail_account_id"] = detail
    return out


def draft(api: Api, b: Books, lines: list[dict], when: date = IN_1405, desc: str = "سند آزمایشی"):
    return api.post(
        "/api/v1/accounting/vouchers",
        {
            "branch_id": b.branch,
            "document_date": when.isoformat(),
            "description": desc,
            "lines": lines,
        },
        idem=new_key(),
    )


def final(api: Api, b: Books, lines: list[dict], when: date = IN_1405) -> dict:
    v = draft(api, b, lines, when)
    assert v.status_code == 201, v.get_json()
    body = v.get_json()
    f = api.post(
        f"/api/v1/accounting/vouchers/{body['id']}/finalize",
        headers={"If-Match": body["row_version"]},
    )
    assert f.status_code == 200, f.get_json()
    return f.get_json()


def sale(b: Books, amount: str = "1000000") -> list[dict]:
    return [line(b.acc["1101"], debit=amount), line(b.acc["5101"], credit=amount)]


# --- chart & rules ------------------------------------------------------------


def test_default_chart_and_rules(accountant: Api, books: Books) -> None:
    accounts = accountant.get("/api/v1/accounting/accounts").get_json()
    by_code = {a["code"]: a for a in accounts}
    assert by_code["1"]["level"] == "group"
    assert by_code["11"]["level"] == "general"
    assert by_code["1101"]["level"] == "subsidiary"
    assert by_code["1201"]["requires_detail"] is True
    assert by_code["5102"]["nature"] == "debit"  # contra-revenue
    rules = accountant.get("/api/v1/accounting/posting-rules").get_json()
    assert rules and all(r["account_id"] for r in rules)


def test_child_code_must_extend_parent(accountant: Api, books: Books) -> None:
    bad = accountant.post(
        "/api/v1/accounting/accounts",
        {"code": "9901", "name": "حساب نادرست", "parent_id": books.acc["11"]},
        idem=new_key(),
    )
    assert bad.get_json()["error"]["code"] == "invalid_code"
    ok = accountant.post(
        "/api/v1/accounting/accounts",
        {"code": "1105", "name": "صندوق شعبه دو", "parent_id": books.acc["11"]},
        idem=new_key(),
    )
    assert ok.status_code == 201
    assert ok.get_json()["level"] == "subsidiary"
    assert ok.get_json()["category"] == "asset"


# --- vouchers -----------------------------------------------------------------


def test_draft_finalize_numbering(accountant: Api, books: Books) -> None:
    v = draft(
        accountant,
        books,
        [line(books.acc["1101"], debit="500000"), line(books.acc["5101"], credit="400000")],
    )
    assert v.status_code == 201
    body = v.get_json()
    assert body["status"] == "draft" and body["number"] is None and body["is_balanced"] is False
    bad = accountant.post(
        f"/api/v1/accounting/vouchers/{body['id']}/finalize",
        headers={"If-Match": body["row_version"]},
    )
    assert bad.get_json()["error"]["code"] == "unbalanced"

    fixed = accountant.send(
        "PUT",
        f"/api/v1/accounting/vouchers/{body['id']}",
        {
            "branch_id": books.branch,
            "document_date": IN_1405.isoformat(),
            "lines": sale(books, "500000"),
        },
        {"If-Match": body["row_version"]},
    )
    assert fixed.status_code == 200, fixed.get_json()
    f = accountant.post(
        f"/api/v1/accounting/vouchers/{body['id']}/finalize",
        headers={"If-Match": fixed.get_json()["row_version"]},
    )
    assert f.status_code == 200
    assert f.get_json()["number"] == 1
    assert f.get_json()["total_debit"] == "500000.0000"
    assert final(accountant, books, sale(books))["number"] == 2


def test_final_voucher_cannot_change_via_api(accountant: Api, books: Books) -> None:
    v = final(accountant, books, sale(books))
    put = accountant.send(
        "PUT",
        f"/api/v1/accounting/vouchers/{v['id']}",
        {
            "branch_id": books.branch,
            "document_date": IN_1405.isoformat(),
            "lines": sale(books, "1"),
        },
        {"If-Match": v["row_version"]},
    )
    assert put.get_json()["error"]["code"] == "voucher_final"
    delete = accountant.send(
        "DELETE", f"/api/v1/accounting/vouchers/{v['id']}", None, {"If-Match": v["row_version"]}
    )
    assert delete.get_json()["error"]["code"] == "voucher_final"


def test_final_voucher_cannot_change_in_database(app: Flask, accountant: Api, books: Books) -> None:
    v = final(accountant, books, sale(books))
    statements = [
        f"UPDATE voucher_line SET debit = 1 WHERE voucher_id = '{v['id']}' AND debit > 0",
        f"DELETE FROM voucher_line WHERE voucher_id = '{v['id']}'",
        f"UPDATE voucher SET description = N'دستکاری' WHERE id = '{v['id']}'",
        f"DELETE FROM voucher WHERE id = '{v['id']}'",
        f"UPDATE voucher SET status = 'draft' WHERE id = '{v['id']}'",
    ]
    with app.app_context():
        for sql in statements:
            s = new_session()
            try:
                with pytest.raises(
                    DBAPIError, match="immutable|cannot be deleted|REFERENCE constraint"
                ):
                    s.execute(text(sql))
            finally:
                s.rollback()
                s.close()


def test_database_rejects_unbalanced_finalisation(
    app: Flask, accountant: Api, books: Books
) -> None:
    body = draft(
        accountant,
        books,
        [line(books.acc["1101"], debit="10"), line(books.acc["5101"], credit="9")],
    ).get_json()
    with app.app_context():
        s = new_session()
        try:
            with pytest.raises(DBAPIError, match="unbalanced"):
                s.execute(
                    text(f"UPDATE voucher SET status='final', number=999 WHERE id='{body['id']}'")
                )
        finally:
            s.rollback()
            s.close()


def test_line_validation(accountant: Api, books: Books) -> None:
    group = draft(
        accountant, books, [line(books.acc["1"], debit="1"), line(books.acc["5101"], credit="1")]
    )
    assert group.get_json()["error"]["code"] == "account_not_postable"
    no_detail = draft(
        accountant, books, [line(books.acc["1201"], debit="1"), line(books.acc["5101"], credit="1")]
    )
    assert no_detail.get_json()["error"]["code"] == "detail_required"
    both = draft(
        accountant,
        books,
        [line(books.acc["1101"], debit="1", credit="1"), line(books.acc["5101"], credit="1")],
    )
    assert both.get_json()["error"]["code"] == "one_side_required"
    as_float = accountant.post(
        "/api/v1/accounting/vouchers",
        {
            "branch_id": books.branch,
            "document_date": IN_1405.isoformat(),
            "lines": [{"account_id": books.acc["1101"], "debit": 0.1}],
        },
        idem=new_key(),
    )
    assert as_float.status_code == 400
    too_precise = draft(
        accountant,
        books,
        [line(books.acc["1101"], debit="1.00001"), line(books.acc["5101"], credit="1.00001")],
    )
    assert too_precise.status_code == 400
    with_detail = draft(
        accountant,
        books,
        [
            line(books.acc["1201"], debit="1", detail=books.customer),
            line(books.acc["5101"], credit="1"),
        ],
    )
    assert with_detail.status_code == 201


def test_reversal(accountant: Api, books: Books) -> None:
    v = final(accountant, books, sale(books, "250000"))
    r = accountant.post(
        f"/api/v1/accounting/vouchers/{v['id']}/reverse", {}, headers={"If-Match": v["row_version"]}
    )
    assert r.status_code == 201, r.get_json()
    rev = r.get_json()
    assert rev["status"] == "final" and rev["reversal_of_id"] == v["id"]
    assert rev["number"] == v["number"] + 1
    assert [(ln["debit"], ln["credit"]) for ln in rev["lines"]] == [
        (ln["credit"], ln["debit"]) for ln in v["lines"]
    ]
    original = accountant.get(f"/api/v1/accounting/vouchers/{v['id']}").get_json()
    assert original["reversed_by_id"] == rev["id"]
    again = accountant.post(
        f"/api/v1/accounting/vouchers/{v['id']}/reverse",
        {},
        headers={"If-Match": original["row_version"]},
    )
    assert again.get_json()["error"]["code"] == "already_reversed"
    tb = accountant.get(
        f"/api/v1/accounting/reports/trial-balance?fiscal_year_id={books.fy}"
    ).get_json()
    cash = next(r for r in tb["rows"] if r["code"] == "1101")
    assert cash["turnover_debit"] == cash["turnover_credit"] == "250000.0000"
    assert cash["balance_debit"] == cash["balance_credit"] == "0.0000"


def test_locked_period_blocks_vouchers(accountant: Api, books: Books) -> None:
    years = accountant.get("/api/v1/accounting/fiscal-years").get_json()
    mehr = next(p for p in years[0]["periods"] if p["number"] == 7)
    lock = accountant.send(
        "PUT",
        f"/api/v1/accounting/fiscal-periods/{mehr['id']}/lock",
        {"is_locked": True},
        {"If-Match": mehr["row_version"]},
    )
    assert lock.status_code == 200
    blocked = draft(accountant, books, sale(books))
    assert blocked.get_json()["error"]["code"] == "period_locked"
    other_month = draft(accountant, books, sale(books), when=date(2026, 8, 1))
    assert other_month.status_code == 201


def test_no_fiscal_year(accountant: Api, books: Books) -> None:
    resp = draft(accountant, books, sale(books), when=date(2030, 1, 1))
    assert resp.get_json()["error"]["code"] == "no_fiscal_year"


def test_create_voucher_is_idempotent(accountant: Api, books: Books) -> None:
    key = new_key()
    body = {"branch_id": books.branch, "document_date": IN_1405.isoformat(), "lines": sale(books)}
    a = accountant.post("/api/v1/accounting/vouchers", body, idem=key)
    b = accountant.post("/api/v1/accounting/vouchers", body, idem=key)
    assert a.get_json()["id"] == b.get_json()["id"]
    page = accountant.get("/api/v1/accounting/vouchers").get_json()
    assert page["total"] == 1


def test_branch_scope_on_vouchers(app: Flask, accountant: Api, books: Books, seed: Seed) -> None:
    v_b = accountant.post(
        "/api/v1/accounting/vouchers",
        {
            "branch_id": str(seed.branch_b),
            "document_date": IN_1405.isoformat(),
            "lines": sale(books),
        },
        idem=new_key(),
    ).get_json()
    make_user(app, "acc_a", ["ACC"], [seed.branch_a])
    a = Api(app.test_client())
    a.login("acc_a")
    assert a.get(f"/api/v1/accounting/vouchers/{v_b['id']}").status_code == 404
    assert a.get("/api/v1/accounting/vouchers").get_json()["total"] == 0
    cross = a.post(
        "/api/v1/accounting/vouchers",
        {
            "branch_id": str(seed.branch_b),
            "document_date": IN_1405.isoformat(),
            "lines": sale(books),
        },
        idem=new_key(),
    )
    assert cross.status_code == 404


def test_concurrent_finalisation_gets_distinct_numbers(
    app: Flask, accountant: Api, books: Books
) -> None:
    ids = [draft(accountant, books, sale(books)).get_json()["id"] for _ in range(6)]
    numbers: list[int] = []
    errors: list[BaseException] = []

    def work(vid: str) -> None:
        try:
            with app.app_context(), unit_of_work() as s:
                v = s.get(Voucher, uuid.UUID(vid))
                assert v is not None
                finalize_voucher(s, v, None)
                numbers.append(int(v.number or 0))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=work, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert sorted(numbers) == [1, 2, 3, 4, 5, 6]


# --- reports ------------------------------------------------------------------


def test_trial_balance_levels_and_opening(accountant: Api, books: Books) -> None:
    final(
        accountant,
        books,
        [
            line(books.acc["1103"], debit="50000000", detail=books.bank),
            line(books.acc["4101"], credit="50000000"),
        ],
        when=date(2026, 4, 1),
    )
    final(accountant, books, sale(books, "3000000"))
    final(
        accountant,
        books,
        [line(books.acc["7102"], debit="1200000"), line(books.acc["1101"], credit="1200000")],
    )
    url = f"/api/v1/accounting/reports/trial-balance?fiscal_year_id={books.fy}"
    sub = accountant.get(url).get_json()
    assert sub["is_balanced"]
    assert sub["totals"]["turnover_debit"] == "54200000.0000"
    groups = accountant.get(url + "&level=group").get_json()
    assert [r["code"] for r in groups["rows"]] == ["1", "4", "5", "7"]
    assets = next(r for r in groups["rows"] if r["code"] == "1")
    assert assets["balance_debit"] == "51800000.0000"
    # From Mehr 1: the capital voucher (Farvardin) becomes opening balance.
    ranged = accountant.get(url + f"&level=group&date_from={MEHR_1405.isoformat()}").get_json()
    assert ranged["is_balanced"]
    equity = next(r for r in ranged["rows"] if r["code"] == "4")
    assert equity["opening_credit"] == "50000000.0000"
    assert equity["turnover_credit"] == "0.0000"


def test_ledger_running_balance_across_pages(accountant: Api, books: Books) -> None:
    for amount in ("100", "200", "300", "400"):
        final(accountant, books, sale(books, amount))
    base = (
        f"/api/v1/accounting/reports/ledger?fiscal_year_id={books.fy}"
        f"&account_id={books.acc['1101']}"
    )
    full = accountant.get(base).get_json()
    assert [r["balance"] for r in full["rows"]] == ["100.0000", "300.0000", "600.0000", "1000.0000"]
    assert full["closing_balance"] == "1000.0000"
    page2 = accountant.get(base + "&page=2&page_size=2").get_json()
    assert [r["balance"] for r in page2["rows"]] == ["600.0000", "1000.0000"]
    # A general (کل) account includes its subsidiaries.
    general = accountant.get(
        f"/api/v1/accounting/reports/ledger?fiscal_year_id={books.fy}&account_id={books.acc['11']}"
    ).get_json()
    assert general["closing_balance"] == "1000.0000"


def test_reports_need_permission(app: Flask, books: Books, seed: Seed) -> None:
    make_user(app, "cashier", ["CSH"])
    c = Api(app.test_client())
    c.login("cashier")
    assert (
        c.get(f"/api/v1/accounting/reports/trial-balance?fiscal_year_id={books.fy}").status_code
        == 403
    )
    assert c.get("/api/v1/accounting/vouchers").status_code == 403


# --- posting engine -----------------------------------------------------------


def test_posting_engine_creates_final_voucher(app: Flask, books: Books) -> None:
    with app.app_context(), unit_of_work() as s:
        v = post_event(
            s,
            event_type="sales.invoice.finalized",
            document_date=IN_1405,
            branch_id=uuid.UUID(books.branch),
            actor_id=None,
            source_ref="INV-1",
            entries=[
                Entry("cash", debit=D("1090000")),
                Entry("revenue", credit=D("1000000")),
                Entry("vat_payable", credit=D("90000")),
                Entry("cogs", debit=D("700000")),
                Entry("inventory", credit=D("700000")),
                Entry("discount", debit=D("0")),
            ],
        )
        assert v.status == "final" and v.number == 1 and v.source_type == "auto"
        codes = {s.get(Account, ln.account_id).code: (ln.debit, ln.credit) for ln in v.lines}  # type: ignore[union-attr]
        assert codes == {
            "1101": (D("1090000"), 0),
            "5101": (0, D("1000000")),
            "3201": (0, D("90000")),
            "6101": (D("700000"), 0),
            "1301": (0, D("700000")),
        }


def test_posting_engine_fails_closed(app: Flask, books: Books) -> None:
    with app.app_context():
        with pytest.raises(DomainError) as missing, unit_of_work() as s:
            s.execute(text("DELETE FROM posting_rule WHERE line_role = 'vat_payable'"))
            post_event(
                s,
                event_type="sales.invoice.finalized",
                document_date=IN_1405,
                branch_id=None,
                actor_id=None,
                entries=[Entry("cash", debit=D("10")), Entry("vat_payable", credit=D("10"))],
            )
        assert missing.value.code == "posting_rule_missing"
        with pytest.raises(DomainError) as unbalanced, unit_of_work() as s:
            post_event(
                s,
                event_type="sales.invoice.finalized",
                document_date=IN_1405,
                branch_id=None,
                actor_id=None,
                entries=[Entry("cash", debit=D("10")), Entry("revenue", credit=D("9"))],
            )
        assert unbalanced.value.code == "unbalanced"
        s = new_session()
        try:
            assert s.scalar(select(Voucher.id)) is None  # both rolled back
            assert s.scalar(select(PostingRule.id).where(PostingRule.line_role == "vat_payable"))
        finally:
            s.close()


# --- year end -----------------------------------------------------------------


def test_close_year_produces_opening_balances(accountant: Api, books: Books) -> None:
    final(
        accountant,
        books,
        [
            line(books.acc["1103"], debit="50000000", detail=books.bank),
            line(books.acc["4101"], credit="50000000"),
        ],
        when=date(2026, 4, 1),
    )
    final(accountant, books, sale(books, "8000000"))
    final(
        accountant,
        books,
        [line(books.acc["7102"], debit="3000000"), line(books.acc["1101"], credit="3000000")],
    )
    draft(accountant, books, sale(books, "1"))
    blocked = accountant.post(f"/api/v1/accounting/fiscal-years/{books.fy}/close")
    assert blocked.get_json()["error"]["code"] == "drafts_exist"
    pending = accountant.get("/api/v1/accounting/vouchers?status=draft").get_json()["items"][0]
    accountant.send(
        "DELETE",
        f"/api/v1/accounting/vouchers/{pending['id']}",
        None,
        {
            "If-Match": accountant.get(f"/api/v1/accounting/vouchers/{pending['id']}").get_json()[
                "row_version"
            ]
        },
    )

    closed = accountant.post(f"/api/v1/accounting/fiscal-years/{books.fy}/close")
    assert closed.status_code == 200, closed.get_json()
    result = closed.get_json()
    assert result["profit"] == "5000000.0000"
    assert result["fiscal_year"]["status"] == "closed"

    years = {
        y["jalali_year"]: y for y in accountant.get("/api/v1/accounting/fiscal-years").get_json()
    }
    new_fy = years[1406]["id"]
    tb = accountant.get(
        f"/api/v1/accounting/reports/trial-balance?fiscal_year_id={new_fy}"
    ).get_json()
    balances = {r["code"]: (r["balance_debit"], r["balance_credit"]) for r in tb["rows"]}
    assert balances == {
        "1101": ("5000000.0000", "0.0000"),
        "1103": ("50000000.0000", "0.0000"),
        "4101": ("0.0000", "50000000.0000"),
        "4201": ("0.0000", "5000000.0000"),
    }
    assert tb["is_balanced"]
    # Old year: everything is zero once closing vouchers are included, and it is locked.
    old = accountant.get(
        f"/api/v1/accounting/reports/trial-balance?fiscal_year_id={books.fy}&include_closing=true"
    ).get_json()
    assert all(r["balance_debit"] == r["balance_credit"] == "0.0000" for r in old["rows"])
    late = draft(accountant, books, sale(books))
    assert late.get_json()["error"]["code"] == "fiscal_year_closed"
    again = accountant.post(f"/api/v1/accounting/fiscal-years/{books.fy}/close")
    assert again.get_json()["error"]["code"] == "fiscal_year_closed"
