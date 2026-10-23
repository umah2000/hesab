"""SEP central PC-POS driver (ADR-0024) against a stand-in built from Saman's document.

No database: these check what the driver sends and how it reads each documented answer.
The real service is not tested here (open-questions Q1).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.sales.services import sep_pcpos
from app.modules.sales.services.sep_pcpos import SepCentralAdapter, SepClient, SepConfig
from tests.sep_fake import CLIENT, USER, FakeSep, approved, fail, ok

AMOUNT = Decimal("110000.0000")


@pytest.fixture
def sep() -> Iterator[FakeSep]:
    fake = FakeSep()
    sep_pcpos._tokens.clear()
    yield fake
    fake.close()


def adapter(fake: FakeSep, timeout: float = 5.0) -> SepCentralAdapter:
    cfg = SepConfig(fake.url, fake.url, *CLIENT, *USER, timeout=timeout)
    return SepCentralAdapter(SepClient(cfg), "1371")


def test_an_approved_payment_sends_what_the_document_asks(sep: FakeSep) -> None:
    a = adapter(sep)
    ref = a.prepare()
    rid = uuid.uuid4()
    r = a.start_sale(rid, ref, AMOUNT, None)
    assert (r.status, r.rrn, r.trace_no, r.response_code) == (
        "Approved",
        "802151113805",
        "500540",
        "00",
    )
    assert r.masked_pan is None  # nothing about the card is kept
    token, ident, pay = sep.calls
    assert token.body == {
        "grant_type": "password",
        "username": USER[0],
        "password": USER[1],
        "scope": "switchapimanagement offline_access",
    }
    assert ident.path == "/v1/PcPosTransaction/ReciveIdentifier"
    assert pay.path == "/v1/PcPosTransaction/StartPayment"
    assert pay.body == {
        "TerminalID": "1371",
        "Amount": "110000",
        "AccountType": 0,
        "TransactionType": 0,
        "Identifier": ref,
        "ResNum": rid.hex,
    }
    # One token for both calls.
    assert sep.tokens_issued == 1


def test_a_rejected_token_is_renewed_once(sep: FakeSep) -> None:
    a = adapter(sep)
    a.prepare()
    sep.expire_next_token = True
    a.prepare()
    assert sep.ops() == [
        "token",
        "ReciveIdentifier",
        "ReciveIdentifier",
        "token",
        "ReciveIdentifier",
    ]
    assert sep.tokens_issued == 2


@pytest.mark.parametrize(
    ("answer", "status", "code"),
    [
        (fail(51, "insufficient"), "Declined", "51"),
        (fail(55), "Declined", "55"),
        (fail(98, "لغو عملیات توسط کاربر"), "Declined", "98"),
        # Not certain the card was not charged: Unknown, so an inquiry decides.
        (fail(97, "عدم ارتباط با مرکز"), "Unknown", "97"),
        (fail(99), "Unknown", "99"),
        (fail(96, "Internal Server Error"), "Unknown", "96"),
        (fail(9, "Duplicate request"), "Unknown", "9"),
        (fail(8), "Unknown", "8"),  # "not found" settles only an inquiry
        (ok({"ResponseCode": "51"}), "Declined", "51"),
        (ok({"ResponseCode": "77"}), "Unknown", "77"),
        (ok(None), "Unknown", None),
    ],
)
def test_answers_that_are_not_an_approval(
    sep: FakeSep, answer: dict[str, object], status: str, code: str | None
) -> None:
    sep.pay = lambda body: (200, answer)
    a = adapter(sep)
    r = a.start_sale(uuid.uuid4(), a.prepare(), AMOUNT, None)
    assert (r.status, r.response_code) == (status, code)
    assert sep_pcpos.message("51") == "موجودی کافی نیست"


def test_an_approval_for_another_amount_or_terminal_is_not_taken(sep: FakeSep) -> None:
    a = adapter(sep)
    sep.pay = lambda body: (200, approved(body, amount="11000"))
    r = a.start_sale(uuid.uuid4(), a.prepare(), AMOUNT, None)
    assert r.status == "ReconciliationRequired"
    sep.pay = lambda body: (200, approved(body | {"TerminalID": "9999"}))
    r = a.start_sale(uuid.uuid4(), a.prepare(), AMOUNT, None)
    assert r.status == "ReconciliationRequired"


def test_server_errors_and_bad_requests(sep: FakeSep) -> None:
    a = adapter(sep)
    sep.pay = lambda body: (500, {"Message": "An error has occurred."})
    assert a.start_sale(uuid.uuid4(), a.prepare(), AMOUNT, None).status == "Unknown"
    # 400 = the request itself was refused (ModelState): nothing was started.
    sep.pay = lambda body: (400, {"Message": "The request is invalid.", "ModelState": {}})
    r = a.start_sale(uuid.uuid4(), a.prepare(), AMOUNT, None)
    assert (r.status, r.response_code) == ("Declined", "HTTP400")


def test_no_answer_in_time_is_unknown_and_the_inquiry_never_cancels(sep: FakeSep) -> None:
    a = adapter(sep, timeout=0.5)
    sep.pay_delay = 2.0
    rid = uuid.uuid4()
    ref = a.prepare()
    r = a.start_sale(rid, ref, AMOUNT, None)
    assert (r.status, r.response_code) == ("Unknown", "NOANSWER")

    # The device had approved after all.
    sep.inquiry = lambda body: (200, approved(body, amount="110000"))
    r = a.inquire(rid, ref, AMOUNT, "NOANSWER")
    assert (r.status, r.rrn) == ("Approved", "802151113805")
    inq = sep.calls[-1]
    assert inq.path == "/v1/PcPosTransaction/Inquery"
    # Leaving CancelPendingRequest out would cancel the payment (document, note 3).
    assert inq.body == {
        "Identifier": ref,
        "ResNum": rid.hex,
        "TerminalID": "1371",
        "CancelPendingRequest": False,
    }


def test_inquiry_answers(sep: FakeSep) -> None:
    a = adapter(sep)
    rid, ref = uuid.uuid4(), a.prepare()
    sep.inquiry = lambda body: (200, fail(8, "transaction not found"))
    assert a.inquire(rid, ref, AMOUNT, "NOANSWER").status == "Declined"
    sep.inquiry = lambda body: (200, fail(97))
    r = a.inquire(rid, ref, AMOUNT, "NOANSWER")
    assert (r.status, r.response_code) == ("Unknown", "97")
    sep.inquiry = lambda body: (200, ok({"ResponseCode": "98"}))
    assert a.inquire(rid, ref, AMOUNT, None).status == "Declined"
    # The service cannot be reached: still Unknown, the last code kept.
    sep.close()
    r = a.inquire(rid, ref, AMOUNT, "97")
    assert (r.status, r.response_code) == ("Unknown", "97")


def test_cancel_is_an_inquiry_that_asks_to_cancel(sep: FakeSep) -> None:
    a = adapter(sep)
    rid, ref = uuid.uuid4(), a.prepare()
    sep.inquiry = lambda body: (200, fail(98, "لغو عملیات توسط کاربر"))
    assert a.inquire(rid, ref, AMOUNT, None, cancel=True).status == "Declined"
    assert sep.calls[-1].body["CancelPendingRequest"] is True


def test_no_identifier_means_nothing_was_sent(sep: FakeSep) -> None:
    a = adapter(sep)
    sep.close()
    with pytest.raises(sep_pcpos.SepError):
        a.prepare()


def settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "mssql+pyodbc://x",
        "secret_key": "k",
        "sep_pcpos_url": "https://sep.example/",
        "sep_pcpos_identity_url": "https://sep.example:44343",
        "sep_pcpos_client_id": "c",
        "sep_pcpos_client_secret": SecretStr("s"),
        "sep_pcpos_username": "u",
        "sep_pcpos_password": SecretStr("p"),
    }
    return Settings(**(base | kw))  # type: ignore[arg-type]


def test_configuration_checks() -> None:
    good = settings()
    assert sep_pcpos.config_problem(good) is None
    assert sep_pcpos.config_from(good).url == "https://sep.example"
    missing = sep_pcpos.config_problem(settings(sep_pcpos_password=None))
    assert missing and "NEXTCAM_SEP_PCPOS_PASSWORD" in missing
    plain = settings(sep_pcpos_url="http://10.0.0.5:8024")
    assert "NEXTCAM_SEP_PCPOS_ALLOW_HTTP" in (sep_pcpos.config_problem(plain) or "")
    allowed = settings(sep_pcpos_url="http://10.0.0.5:8024", sep_pcpos_allow_http=True)
    assert sep_pcpos.config_problem(allowed) is None
    with pytest.raises(ValueError, match="https"):
        settings(sep_pcpos_url="ftp://x")
