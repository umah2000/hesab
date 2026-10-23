"""Saman (SEP) central PC-POS driver (ADR-0024).

Built only from Saman Kish's «راهنمای پیاده‌سازی سرویس‌های پی سی پوز مرکزی», v1.4
(1399/05/29). Nothing beyond that document is assumed:

* Token: ``POST {identity}/ids/connect/token``, OAuth2 password grant with the client's
  Basic authentication, scope ``switchapimanagement offline_access``.
* ``POST {service}/v1/PcPosTransaction/ReciveIdentifier``: an id for one attempt.
* ``StartPayment``: TerminalID, Amount, AccountType 0 (Single), TransactionType 0
  (Purchase), Identifier, ResNum (ours, at most 50). It answers once the device is done.
* ``Inquery``: Identifier and TerminalID. ``CancelPendingRequest`` false only asks; true,
  **or leaving it out**, cancels a request still waiting for the card (note 3). So it is
  always sent explicitly.
* Every answer is ``{IsSuccess, ErrorCode, ErrorDescription, Data}``.

Whatever the document leaves open is Unknown, never Declined: the money may have been
taken, and only an inquiry or the bank's report can tell. Card data is never read,
kept or logged; only the reference numbers.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.config import Settings
from app.modules.sales.services.card_adapter import AdapterResult

log = logging.getLogger(__name__)

SCOPE = "switchapimanagement offline_access"
PATH = "/v1/PcPosTransaction/"
INQUIRY_TIMEOUT = 20.0

# Table 2 of the document (response codes).
MESSAGES: dict[str, str] = {
    "0": "تراکنش با موفقیت انجام پذیرفت",
    "00": "تراکنش با موفقیت انجام پذیرفت",
    "1": "کارت کشیده شد",
    "2": "مبلغ تراکنش نمی‌تواند از حداقل مبلغ کوچک‌تر باشد",
    "3": "عدم ارتباط با دستگاه",
    "4": "اطلاعات نامعتبر",
    "5": "صفر ریال بدهی",
    "6": "خطا در دریافت اطلاعات",
    "7": "عدم دسترسی به این عملیات",
    "8": "تراکنش یافت نشد",
    "9": "ترمینال نامعتبر",
    "10": "خطا در پاسخ",
    "12": "تراکنش نامعتبر",
    "13": "مبلغ نامعتبر",
    "14": "خطا در مقداردهی",
    "20": "پاسخ نامعتبر",
    "26": "خطا در تراکنش",
    "27": "این قبض قبلاً پرداخت شده است",
    "28": "غیرقابل پرداخت",
    "30": "خطا در قالب اطلاعات",
    "33": "تاریخ انقضای کارت سپری شده است",
    "34": "اخطار امنیتی",
    "38": "تعداد دفعات ورود رمز غلط بیش از حد مجاز است",
    "43": "اخطار امنیتی",
    "51": "موجودی کافی نیست",
    "55": "رمز کارت نامعتبر است",
    "57": "انجام تراکنش توسط دارنده‌ی کارت مجاز نیست",
    "58": "انجام تراکنش توسط پایانه مجاز نیست",
    "61": "مبلغ تراکنش بیش از حد مجاز است",
    "63": "اخطار امنیتی",
    "68": "عدم دریافت پاسخ در زمان مناسب",
    "69": "تعداد دفعات ورود رمز غلط بیش از حد مجاز است",
    "75": "تعداد دفعات ورود رمز غلط بیش از حد مجاز است",
    "78": "کارت غیرفعال است",
    "79": "مبلغ نامعتبر",
    "80": "عدم پاسخ از سوی صادرکننده‌ی کارت",
    "84": "عدم پاسخ از سوی صادرکننده‌ی کارت",
    "91": "عدم پاسخ از سوی صادرکننده‌ی کارت",
    "92": "مبالغ متفاوت",
    "96": "خطای نامشخص",
    "97": "عدم ارتباط با مرکز",
    "98": "لغو عملیات توسط کاربر",
    "99": "عدم دریافت پاسخ در زمان مناسب در کارت‌خوان",
    "100": "وضعیت حساب نامعتبر است",
}

# Codes after which the card was certainly not charged: the request was refused before
# it reached the card, the card's bank refused it, or the customer cancelled. Everything
# else (no answer, "unknown error", 97 "no connection with the centre", which the
# document says to inquire about, and 9, which its example uses for "Duplicate request")
# stays Unknown.
DECLINED = frozenset(
    [
        "2",
        "4",
        "5",
        "7",
        "12",
        "13",
        "14",
        "27",
        "28",
        "30",
        "33",
        "34",
        "38",
        "43",
        "51",
        "55",
        "57",
        "58",
        "61",
        "63",
        "69",
        "75",
        "78",
        "79",
        "92",
        "98",
        "100",
    ]
)
APPROVED = frozenset({"0", "00"})
NOT_FOUND = "8"


def message(code: str | None) -> str | None:
    return MESSAGES.get(code) if code else None


class SepError(Exception):
    """No usable answer: connection, timeout, server error or an unreadable reply."""


class SepRefused(Exception):
    """HTTP 400: the service rejected the request itself, so nothing was started."""


@dataclass(frozen=True)
class SepConfig:
    url: str
    identity_url: str
    client_id: str
    client_secret: str
    username: str
    password: str
    timeout: float


def config_problem(settings: Settings) -> str | None:
    """Why the program cannot reach the service yet (Persian, shown as is), or None."""
    missing = [
        name
        for name, value in (
            ("NEXTCAM_SEP_PCPOS_URL", settings.sep_pcpos_url),
            ("NEXTCAM_SEP_PCPOS_IDENTITY_URL", settings.sep_pcpos_identity_url),
            ("NEXTCAM_SEP_PCPOS_CLIENT_ID", settings.sep_pcpos_client_id),
            ("NEXTCAM_SEP_PCPOS_CLIENT_SECRET", settings.sep_pcpos_client_secret),
            ("NEXTCAM_SEP_PCPOS_USERNAME", settings.sep_pcpos_username),
            ("NEXTCAM_SEP_PCPOS_PASSWORD", settings.sep_pcpos_password),
        )
        if not value
    ]
    if missing:
        return (
            "نشانی و اطلاعات ورود سرویس پی‌سی‌پوز مرکزی سامان روی سرور تنظیم نشده است: "
            + "، ".join(missing)
        )
    urls = (settings.sep_pcpos_url or "", settings.sep_pcpos_identity_url or "")
    if not settings.sep_pcpos_allow_http and any(u.startswith("http://") for u in urls):
        return (
            "نشانی سرویس سامان https نیست. اگر سامان سرویس را بدون TLS در شبکه‌ی داخلی داده "
            "است، NEXTCAM_SEP_PCPOS_ALLOW_HTTP=true را تنظیم کنید."
        )
    return None


def config_from(settings: Settings) -> SepConfig:
    assert settings.sep_pcpos_client_secret and settings.sep_pcpos_password
    return SepConfig(
        url=settings.sep_pcpos_url or "",
        identity_url=settings.sep_pcpos_identity_url or "",
        client_id=settings.sep_pcpos_client_id or "",
        client_secret=settings.sep_pcpos_client_secret.get_secret_value(),
        username=settings.sep_pcpos_username or "",
        password=settings.sep_pcpos_password.get_secret_value(),
        timeout=float(settings.sep_pcpos_timeout_seconds),
    )


# The service is on the shop's or Saman's network: never through a system proxy.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# One token per account, shared by all requests of this process until shortly before
# it expires (the document: one hour in the test environment).
_tokens: dict[tuple[str, str, str], tuple[str, float]] = {}
_token_lock = threading.Lock()


def _lower(d: Any) -> dict[str, Any]:
    return {str(k).lower(): v for k, v in d.items()} if isinstance(d, dict) else {}


class SepClient:
    def __init__(self, cfg: SepConfig) -> None:
        self.cfg = cfg

    def _post(
        self, url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
        try:
            with _opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 400:
                raise SepRefused(str(e.code)) from None
            raise SepError(f"http {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SepError(type(e).__name__) from None
        try:
            data = json.loads(raw)
        except ValueError:
            raise SepError("unreadable answer") from None
        if not isinstance(data, dict):
            raise SepError("unreadable answer")
        return data

    def _token(self, fresh: bool = False) -> str:
        key = (self.cfg.identity_url, self.cfg.client_id, self.cfg.username)
        with _token_lock:
            hit = _tokens.get(key)
            # Not one that may expire while the customer is still at the device.
            if hit and not fresh and hit[1] - time.monotonic() > self.cfg.timeout + 30:
                return hit[0]
            basic = base64.b64encode(
                f"{self.cfg.client_id}:{self.cfg.client_secret}".encode()
            ).decode()
            form = urllib.parse.urlencode(
                {
                    "grant_type": "password",
                    "username": self.cfg.username,
                    "password": self.cfg.password,
                    "scope": SCOPE,
                }
            ).encode()
            try:
                answer = _lower(
                    self._post(
                        self.cfg.identity_url + "/ids/connect/token",
                        form,
                        {
                            "Authorization": f"Basic {basic}",
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Accept": "application/json",
                        },
                        INQUIRY_TIMEOUT,
                    )
                )
            except SepRefused:
                raise SepError("token refused") from None
            token = answer.get("access_token")
            if not isinstance(token, str) or not token:
                raise SepError("no token")
            try:
                ttl = float(answer.get("expires_in") or 300)
            except (TypeError, ValueError):
                ttl = 300.0
            _tokens[key] = (token, time.monotonic() + ttl)
            return token

    def call(self, op: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        """One service call; the answer with lower-cased keys (``data`` too)."""
        payload = json.dumps(body).encode()
        for attempt in (0, 1):
            headers = {
                "Authorization": f"Bearer {self._token(fresh=attempt == 1)}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                answer = _lower(self._post(self.cfg.url + PATH + op, payload, headers, timeout))
            except SepError as e:
                # 401 is answered before anything runs: a new token and once more.
                if str(e) == "http 401" and attempt == 0:
                    continue
                raise
            answer["data"] = _lower(answer.get("data"))
            return answer
        raise SepError("unauthorized")


def _code(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _short(value: Any, n: int = 32) -> str | None:
    text = _code(value)
    return text[:n] if text else None


class SepCentralAdapter:
    adapter_id = "sep_central"
    label = "سامان، پی‌سی‌پوز مرکزی"
    # Built from the document; not yet run against Saman's test service (open-questions Q1).
    verified = False
    simulated = False
    scenarios: tuple[str, ...] = ()
    background = True  # StartPayment waits for the customer
    can_cancel = True

    def __init__(self, client: SepClient, terminal_no: str) -> None:
        self.client = client
        self.terminal_no = terminal_no

    def prepare(self) -> str:
        """The Identifier of a new attempt; nothing is sent to the device yet."""
        r = self.client.call("ReciveIdentifier", {}, INQUIRY_TIMEOUT)
        ident = _code(r["data"].get("identifier"))
        if not r.get("issuccess") or not ident or len(ident) > 64 or not ident.isprintable():
            raise SepError(f"no identifier ({_code(r.get('errorcode'))})")
        return ident

    def start_sale(
        self, request_id: uuid.UUID, provider_ref: str | None, amount: Decimal, scenario: str | None
    ) -> AdapterResult:
        body = {
            "TerminalID": self.terminal_no,
            "Amount": str(int(amount)),
            "AccountType": 0,
            "TransactionType": 0,
            "Identifier": provider_ref,
            "ResNum": request_id.hex,
        }
        try:
            r = self.client.call("StartPayment", body, self.client.cfg.timeout)
        except SepRefused:
            return AdapterResult("Declined", response_code="HTTP400")
        except SepError as e:
            log.warning("SEP StartPayment: no answer (%s)", e)
            return AdapterResult("Unknown", response_code="NOANSWER")
        return self._result(r, amount, inquiry=False)

    def inquire(
        self,
        request_id: uuid.UUID,
        provider_ref: str | None,
        amount: Decimal,
        response_code: str | None,
        cancel: bool = False,
    ) -> AdapterResult:
        body = {
            "Identifier": provider_ref,
            "ResNum": request_id.hex,
            "TerminalID": self.terminal_no,
            "CancelPendingRequest": cancel,  # always explicit: omitting it cancels
        }
        try:
            r = self.client.call("Inquery", body, INQUIRY_TIMEOUT)
        except (SepError, SepRefused) as e:
            log.warning("SEP Inquery: no answer (%s)", e)
            return AdapterResult("Unknown", response_code=response_code)
        return self._result(r, amount, inquiry=True)

    def _result(self, r: dict[str, Any], amount: Decimal, *, inquiry: bool) -> AdapterResult:
        d: dict[str, Any] = r["data"]
        error = _code(r.get("errorcode"))
        if r.get("issuccess") is True and error in ("", "0"):
            code = _code(d.get("responsecode"))
            if code in APPROVED:
                if not self._same(d, amount):
                    log.warning("SEP answer for another amount or terminal")
                    return AdapterResult("ReconciliationRequired", response_code="MISMATCH")
                return AdapterResult(
                    "Approved",
                    rrn=_short(d.get("rrn")),
                    trace_no=_short(d.get("tracenumber")),
                    response_code="00",
                )
            if code in DECLINED:
                return AdapterResult("Declined", response_code=code)
            return AdapterResult("Unknown", response_code=code[:16] or None)
        if error in DECLINED or (inquiry and error == NOT_FOUND):
            return AdapterResult("Declined", response_code=error)
        return AdapterResult("Unknown", response_code=error[:16] or None)

    def _same(self, d: dict[str, Any], amount: Decimal) -> bool:
        """The answer is for this terminal and amount, when it says so."""
        if d.get("amount") not in (None, ""):
            try:
                if Decimal(_code(d["amount"])) != amount:
                    return False
            except InvalidOperation:
                return False
        tid = _code(d.get("terminalid"))
        return not tid or tid == self.terminal_no
