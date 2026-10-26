"""Weighbridge platform (VA) statements → vouchers (ADR-0025), on SQL Server.

The webhook is signed exactly as the platform signs it (integrations/service.py there:
``"sha256=" + HMAC-SHA256(secret, f"{ts}." + body)``)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from flask import Flask
from pydantic import SecretStr
from sqlalchemy import select

from app.core.db import unit_of_work
from app.modules.accounting.models import DetailAccount, Voucher, VoucherLine
from app.modules.accounting.services.chart import seed_defaults
from app.modules.accounting.services.fiscal import ensure_year
from tests.conftest import Seed, make_user
from tests.test_sales import login

SECRET = "va-webhook-secret-for-tests"
TENANT = str(uuid.uuid4())
URL = "/api/v1/integrations/va/webhook"


@pytest.fixture
def va(app: Flask, seed: Seed) -> Iterator[Flask]:
    with app.app_context(), unit_of_work() as s:
        seed_defaults(s)
        ensure_year(s, 1405)
        s.add(DetailAccount(code="HC-01", name="حمل‌ونقل البرز", kind="person", is_active=True))
        s.add(DetailAccount(code="CU-07", name="فولاد کویر", kind="person", is_active=True))
    make_user(app, "acc", ["ACC"])
    settings = app.config["SETTINGS"]
    settings.va_webhook_secret, settings.va_tenant_id = SecretStr(SECRET), TENANT
    try:
        yield app
    finally:
        settings.va_webhook_secret = settings.va_tenant_id = None


def send(
    app: Flask,
    event: str,
    data: dict[str, Any],
    *,
    event_id: str | None = None,
    ts: int | None = None,
    secret: str = SECRET,
    tenant: str = TENANT,
) -> Any:
    payload = {
        "id": event_id or str(uuid.uuid4()),
        "event": event,
        "occurred_at": "2026-10-26T08:00:00+00:00",
        "tenant_id": tenant,
        "data": data,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ts = int(time.time()) if ts is None else ts
    sig = (
        "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    )
    return app.test_client().post(
        URL,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-VA-Event": event,
            "X-VA-Event-Id": payload["id"],
            "X-VA-Timestamp": str(ts),
            "X-VA-Signature": sig,
        },
    )


def statement(kind: str = "haulage", **kw: Any) -> dict[str, Any]:
    """As the platform's approve_settlement emits it."""
    base = {
        "id": str(uuid.uuid4()),
        "number": "HS-000012" if kind == "haulage" else "SS-000004",
        "kind": kind,
        "counterparty": "حمل‌ونقل البرز" if kind == "haulage" else "فولاد کویر",
        "counterparty_code": "H1",
        "accounting_code": "HC-01" if kind == "haulage" else "CU-07",
        "period_start": "2026-09-23",
        "period_end": "2026-10-22",
        "trips": 214,
        "net_kg": "5123400.000",
        "amount": 1_200_000_000,
        "adjustments": [{"label": "کسر بیمه", "amount": -20_000_000}],
        "vat": 118_000_000,
        "total": 1_298_000_000,
    }
    return base | kw


def lines(app: Flask, number: int) -> list[tuple[str, str | None, Decimal, Decimal]]:
    """Sorted (account code, detail code, debit, credit) of voucher ``number``."""
    from app.modules.accounting.models import Account

    with app.app_context(), unit_of_work() as s:
        v = s.scalar(select(Voucher).where(Voucher.number == number))
        assert v is not None and v.status == "final"
        out = []
        for ln in list(s.scalars(select(VoucherLine).where(VoucherLine.voucher_id == v.id))):
            acc = s.get(Account, ln.account_id)
            det = s.get(DetailAccount, ln.detail_account_id) if ln.detail_account_id else None
            assert acc is not None
            out.append((acc.code, det.code if det else None, ln.debit, ln.credit))
        return sorted(out)


def test_signature_clock_and_organisation_are_checked(va: Flask) -> None:
    data = statement()
    assert send(va, "settlement.approved", data, secret="wrong").status_code == 401
    assert send(va, "settlement.approved", data, ts=int(time.time()) - 600).status_code == 401
    assert send(va, "settlement.approved", data, tenant=str(uuid.uuid4())).status_code == 403
    tampered = va.test_client().post(URL, data=b"{}", headers={"X-VA-Timestamp": "1"})
    assert tampered.status_code == 401
    # Nothing was recorded by any of them.
    acc = login(va, "acc")
    assert acc.get("/api/v1/integrations/va/documents").json["total"] == 0
    # Not configured: the endpoint does not exist.
    settings = va.config["SETTINGS"]
    settings.va_webhook_secret = None
    assert send(va, "settlement.approved", data).status_code == 404
    settings.va_webhook_secret = SecretStr(SECRET)
    assert send(va, "webhook.ping", {"message": "pong"}).json["status"] == "ignored"


def test_haulage_and_sales_statements_become_vouchers_once(va: Flask) -> None:
    haul = statement()
    event_id = str(uuid.uuid4())
    r = send(va, "settlement.approved", haul, event_id=event_id)
    assert r.status_code == 200, r.get_json()
    assert r.json["status"] == "posted" and r.json["voucher_number"]
    no = r.json["voucher_number"]
    z = Decimal(0)
    assert lines(va, no) == [
        ("1402", None, Decimal(118_000_000), z),
        ("3101", "HC-01", z, Decimal(1_298_000_000)),
        ("7199", None, z, Decimal(20_000_000)),  # the deduction (default account)
        ("7199", None, Decimal(1_200_000_000), z),
    ]
    # Sent again (VA retry, or a second delivery of the same event): no second voucher.
    again = send(va, "settlement.approved", haul, event_id=event_id)
    assert again.json["status"] == "duplicate" and again.json["voucher_number"] == no
    other_id = send(va, "settlement.approved", haul)
    assert other_id.json["status"] == "duplicate" and other_id.json["voucher_number"] == no

    sale = statement(
        "sales", adjustments=[{"label": "حمل", "amount": 5_000_000}], total=1_323_000_000
    )
    r = send(va, "settlement.approved", sale)
    assert r.json["status"] == "posted", r.get_json()
    assert lines(va, r.json["voucher_number"]) == [
        ("1201", "CU-07", Decimal(1_323_000_000), z),
        ("3201", None, z, Decimal(118_000_000)),
        ("5101", None, z, Decimal(1_200_000_000)),
        ("5103", None, z, Decimal(5_000_000)),
    ]
    with va.app_context(), unit_of_work() as s:
        dated = s.scalar(select(Voucher).where(Voucher.number == no))
        assert dated is not None and dated.document_date.isoformat() == "2026-10-22"


def test_unknown_counterparty_is_held_then_posted_after_the_fix(va: Flask) -> None:
    data = statement(accounting_code="HC-99", counterparty="پیمانکار تازه")
    r = send(va, "settlement.approved", data)
    assert r.status_code == 202 and r.json["status"] == "held"
    assert "HC-99" in r.json["message"]
    acc = login(va, "acc")
    held = acc.get("/api/v1/integrations/va/documents?status=held").json["items"]
    assert [d["number"] for d in held] == ["HS-000012"] and held[0]["voucher_id"] is None
    st = acc.get("/api/v1/integrations/va/status").json
    assert (st["configured"], st["held"]) == (True, 1)
    # Retrying without fixing changes nothing.
    still = acc.post(f"/api/v1/integrations/va/documents/{held[0]['id']}/retry")
    assert still.status_code == 200 and still.json["status"] == "held"
    with va.app_context(), unit_of_work() as s:
        s.add(DetailAccount(code="HC-99", name="پیمانکار تازه", kind="person", is_active=True))
    done = acc.post(f"/api/v1/integrations/va/documents/{held[0]['id']}/retry").json
    assert done["status"] == "posted" and done["voucher_number"] and done["problem"] is None
    nothing = acc.post(f"/api/v1/integrations/va/documents/{held[0]['id']}/retry")
    assert nothing.json["error"]["code"] == "nothing_to_retry"
    # Retry is the accountant's: a cashier-like user without the permission cannot.
    make_user(va, "clerk", ["CSH"])
    assert login(va, "clerk").get("/api/v1/integrations/va/documents").status_code == 403


def test_inconsistent_amounts_are_held_not_guessed(va: Flask) -> None:
    r = send(va, "settlement.approved", statement(total=999))
    assert r.status_code == 202 and "جمع کل" in r.json["message"]
    old = statement()
    del old["period_end"]
    r = send(va, "settlement.approved", old)
    assert r.status_code == 202 and "به‌روز" in r.json["message"]


def test_void_reverses_the_voucher_and_out_of_order_void_wins(va: Flask) -> None:
    data = statement()
    posted = send(va, "settlement.approved", data).json
    void = {"id": data["id"], "number": data["number"], "kind": "haulage", "reason": "وزن اشتباه"}
    r = send(va, "settlement.voided", void)
    assert r.status_code == 200 and r.json["status"] == "reversed", r.get_json()
    rev = r.json["reversal_voucher_number"]
    assert rev and rev != posted["voucher_number"]
    original = lines(va, posted["voucher_number"])
    assert lines(va, rev) == sorted((a, d, c, b) for a, d, b, c in original)
    assert send(va, "settlement.voided", void).json["status"] == "duplicate"

    # Void before approval (webhooks have no order): the late approval is not booked.
    late = statement(number="HS-000013")
    first = send(va, "settlement.voided", {"id": late["id"], "number": "HS-000013"})
    assert first.json["status"] == "voided"
    after = send(va, "settlement.approved", late)
    assert after.json["status"] == "duplicate" and after.json["voucher_number"] is None
    # A held statement that is voided needs nothing more.
    held = statement(number="HS-000014", accounting_code="NOPE")
    assert send(va, "settlement.approved", held).json["status"] == "held"
    assert send(va, "settlement.voided", {"id": held["id"]}).json["status"] == "voided"
    acc = login(va, "acc")
    by_number = {
        d["number"]: d["status"] for d in acc.get("/api/v1/integrations/va/documents").json["items"]
    }
    assert by_number == {"HS-000012": "reversed", "HS-000013": "voided", "HS-000014": "voided"}
