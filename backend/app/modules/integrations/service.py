"""Weighbridge platform (VA) statements → vouchers (ADR-0025).

The platform sends a signed webhook when a statement is approved or voided. Each event is
recorded once (by its id) and its statement posted in the same unit of work through the
posting rules. What cannot be posted yet (unknown counterparty, missing rule, closed
period, inconsistent amounts) is held with the reason, never guessed; the accountant fixes
the cause and posts it again. A void reverses the voucher; nothing is edited or deleted.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import utcnow
from app.core.errors import DomainError, NotFoundError
from app.core.http import Page
from app.modules.accounting.models import DetailAccount, Voucher
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.accounting.services.vouchers import reverse_voucher
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.integrations.models import IntegrationDocument, IntegrationEvent
from app.modules.integrations.schemas import (
    DocumentQuery,
    IntegrationDocumentOut,
    IntegrationEventOut,
    IntegrationStatusOut,
)
from app.modules.inventory.services.stock import tehran_today
from app.modules.organization.models import Branch

SOURCE = "va"
MAX_BODY = 256 * 1024
CLOCK_WINDOW = 300  # seconds between the signature's time and ours
LABEL = {"haulage": "صورت‌وضعیت حمل", "sales": "صورت‌حساب فروش"}
EVENT = {"haulage": "va.haulage", "sales": "va.sales"}


class Rejected(Exception):
    """The request is not a genuine, current webhook of the configured platform."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status, self.code = status, code


@dataclass(frozen=True)
class Delivery:
    event: str
    event_id: str
    occurred_at: datetime | None
    data: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    http_status: int
    body: dict[str, Any]


def configured(settings: Settings) -> bool:
    return bool(settings.va_webhook_secret and settings.va_tenant_id)


def verify(settings: Settings, headers: Any, body: bytes, now: float) -> Delivery:
    """Signature (HMAC-SHA256 over ``"{timestamp}." + body``), clock and organisation."""
    if not configured(settings):
        raise Rejected(404, "not_configured")
    assert settings.va_webhook_secret is not None
    if len(body) > MAX_BODY:
        raise Rejected(413, "too_large")
    try:
        ts = int(headers.get("X-VA-Timestamp", ""))
    except ValueError:
        raise Rejected(401, "bad_signature") from None
    if abs(now - ts) > CLOCK_WINDOW:
        raise Rejected(401, "stale")
    secret = settings.va_webhook_secret.get_secret_value().encode()
    expected = "sha256=" + hmac.new(secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, headers.get("X-VA-Signature", "")):
        raise Rejected(401, "bad_signature")
    try:
        payload = json.loads(body)
    except ValueError:
        raise Rejected(400, "bad_json") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise Rejected(400, "bad_json")
    if str(payload.get("tenant_id")) != settings.va_tenant_id:
        raise Rejected(403, "other_organisation")
    event = str(payload.get("event") or "")
    event_id = str(payload.get("id") or "")
    if not event or not event_id or len(event_id) > 64 or event != headers.get("X-VA-Event"):
        raise Rejected(400, "bad_json")
    occurred = None
    with contextlib.suppress(ValueError):
        occurred = datetime.fromisoformat(str(payload.get("occurred_at")))
    return Delivery(event, event_id, occurred, payload["data"])


# --- statements ----------------------------------------------------------------------


@dataclass(frozen=True)
class Statement:
    id: str
    number: str
    kind: str
    accounting_code: str
    counterparty: str
    period_end: date
    trips: int
    amount: Decimal
    adjustment: Decimal
    vat: Decimal
    total: Decimal


def _rial(v: Any, what: str) -> Decimal:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError(f"مبلغ «{what}» نامعتبر است") from None
    if d != d.to_integral_value():
        raise ValueError(f"مبلغ «{what}» باید ریال کامل باشد")
    return d


def parse_statement(data: dict[str, Any]) -> Statement:
    """The approved statement as the platform sends it; ValueError says what is wrong."""
    kind = data.get("kind")
    if kind not in LABEL:
        raise ValueError("نوع صورت‌وضعیت نامعتبر است")
    code = str(data.get("accounting_code") or "").strip()
    if not code:
        raise ValueError(
            "کد حسابداری (تفصیلی) طرف‌حساب در سامانه باسکول خالی است؛ آن را آن‌جا تکمیل کنید"
        )
    try:
        period_end = date.fromisoformat(str(data.get("period_end")))
    except ValueError:
        raise ValueError(
            "تاریخ پایان دوره‌ی صورت‌وضعیت نیامده است (سامانه باسکول به‌روز نیست)"
        ) from None
    adjustments = data.get("adjustments") or []
    if not isinstance(adjustments, list):
        raise ValueError("کسورات و اضافات نامعتبر است")
    st = Statement(
        id=str(data["id"]),
        number=str(data.get("number") or "")[:32],
        kind=kind,
        accounting_code=code[:48],
        counterparty=str(data.get("counterparty") or "")[:200],
        period_end=period_end,
        trips=int(data.get("trips") or 0),
        amount=_rial(data.get("amount"), "مبلغ"),
        adjustment=sum(
            (_rial(a.get("amount", 0), "کسورات و اضافات") for a in adjustments), Decimal(0)
        ),
        vat=_rial(data.get("vat") or 0, "مالیات"),
        total=_rial(data.get("total"), "جمع کل"),
    )
    if st.amount < 0 or st.vat < 0 or st.total <= 0:
        raise ValueError("مبلغ‌های صورت‌وضعیت نامعتبر یا صفر است")
    if st.amount + st.adjustment + st.vat != st.total:
        raise ValueError(
            "جمع کل با مبلغ، کسورات و اضافات و مالیات نمی‌خواند؛ صورت‌وضعیت را بررسی کنید"
        )
    return st


def _entries(st: Statement, party_id: uuid.UUID) -> list[Entry]:
    adj = st.adjustment
    if st.kind == "haulage":
        out = [Entry("expense", debit=st.amount), Entry("vat_receivable", debit=st.vat)]
        out.append(
            Entry("adjustments", debit=adj) if adj > 0 else Entry("adjustments", credit=-adj)
        )
        out.append(Entry("payable", credit=st.total, detail_account_id=party_id))
        return out
    out = [Entry("receivable", debit=st.total, detail_account_id=party_id)]
    out.append(Entry("adjustments", debit=-adj) if adj < 0 else Entry("adjustments", credit=adj))
    out += [Entry("revenue", credit=st.amount), Entry("vat_payable", credit=st.vat)]
    return out


def _branch_id(s: Session, settings: Settings) -> uuid.UUID | None:
    if not settings.va_branch_code:
        return None
    b = s.scalar(select(Branch.id).where(Branch.code == settings.va_branch_code.upper()))
    if b is None:
        raise ValueError(f"شعبه‌ی {settings.va_branch_code} (NEXTCAM_VA_BRANCH_CODE) یافت نشد")
    return b


def _hold(doc: IntegrationDocument, problem: str) -> None:
    doc.status, doc.problem, doc.updated_at = "held", problem[:500], utcnow()


def _post(s: Session, settings: Settings, doc: IntegrationDocument) -> None:
    """Post a held statement, or keep it held with the reason."""
    try:
        st = parse_statement(json.loads(doc.payload or "{}"))
        branch_id = _branch_id(s, settings)
    except (ValueError, KeyError) as e:
        return _hold(doc, str(e))
    party = s.scalar(select(DetailAccount).where(DetailAccount.code == st.accounting_code))
    if party is None or party.kind != "person" or not party.is_active:
        return _hold(
            doc,
            f"طرف‌حسابی با کد تفصیلی {st.accounting_code} ({st.counterparty}) در NEXTCAM "
            "تعریف نشده یا غیرفعال است؛ آن را در «طرف‌حساب‌ها» تعریف کنید و دوباره ثبت کنید",
        )
    try:
        with s.begin_nested():
            v = post_event(
                s,
                event_type=EVENT[st.kind],
                document_date=st.period_end,
                branch_id=branch_id,
                entries=_entries(st, party.id),
                actor_id=None,
                source_id=doc.id,
                description=f"{LABEL[st.kind]} {st.number} — {party.name} — "
                f"{st.trips} سفر (سامانه باسکول)",
            )
    except DomainError as e:
        return _hold(doc, e.message)
    doc.status, doc.problem, doc.voucher_id, doc.updated_at = "posted", None, v.id, utcnow()


def _reverse(s: Session, doc: IntegrationDocument) -> None:
    """Reverse the voucher of a voided statement; kept posted, with the reason, if not yet."""
    v = s.get(Voucher, doc.voucher_id)
    if v is None:
        return
    try:
        with s.begin_nested():
            rev = reverse_voucher(
                s,
                v,
                None,
                tehran_today(),
                f"برگشت {LABEL.get(doc.kind or '', 'صورت‌وضعیت')} {doc.number} — "
                f"باطل‌شده در سامانه باسکول: {doc.void_reason or ''}"[:300],
            )
    except DomainError as e:
        doc.problem, doc.updated_at = f"ابطال رسید ولی سند برگشت نخورد: {e.message}"[:500], utcnow()
        return
    doc.status, doc.problem, doc.reversal_voucher_id = "reversed", None, rev.id
    doc.updated_at = utcnow()


def _document(s: Session, source_id: str) -> IntegrationDocument | None:
    # Key seek (unique source, kind, id): one webhook at a time per statement.
    return s.scalar(
        select(IntegrationDocument)
        .where(
            IntegrationDocument.source == SOURCE,
            IntegrationDocument.source_kind == "settlement",
            IntegrationDocument.source_id == source_id,
        )
        .with_for_update()
    )


def _fill(doc: IntegrationDocument, data: dict[str, Any]) -> None:
    doc.number = str(data.get("number") or doc.number or "")[:32]
    kind = data.get("kind")
    doc.kind = kind if kind in LABEL else doc.kind
    doc.counterparty_code = str(data.get("accounting_code") or "")[:48] or doc.counterparty_code
    doc.counterparty_name = str(data.get("counterparty") or "")[:200] or doc.counterparty_name
    with contextlib.suppress(ValueError):
        doc.document_date = date.fromisoformat(str(data.get("period_end")))
    with contextlib.suppress(InvalidOperation, ValueError):
        doc.total = Decimal(str(data.get("total")))


def _new(data: dict[str, Any], status: str) -> IntegrationDocument:
    doc = IntegrationDocument(
        source=SOURCE,
        source_kind="settlement",
        source_id=str(data["id"])[:64],
        number="",
        status=status,
    )
    _fill(doc, data)
    return doc


def _approved(
    s: Session, settings: Settings, data: dict[str, Any]
) -> tuple[str, IntegrationDocument]:
    doc = _document(s, str(data["id"]))
    if doc is not None and doc.status != "held":
        # Already in the books, or voided before this approval arrived.
        return "duplicate", doc
    if doc is None:
        doc = _new(data, "held")
        s.add(doc)
        s.flush()
    else:
        _fill(doc, data)
    doc.payload = json.dumps(data, ensure_ascii=False)
    _post(s, settings, doc)
    return doc.status, doc


def _voided(s: Session, data: dict[str, Any]) -> tuple[str, IntegrationDocument]:
    doc = _document(s, str(data["id"]))
    reason = str(data.get("reason") or data.get("void_reason") or "")[:500] or None
    if doc is None:
        # The void came first (webhooks have no order): nothing to reverse, and a late
        # approval of this statement is ignored.
        doc = _new(data, "voided")
        doc.void_reason = reason
        s.add(doc)
        s.flush()
        return "voided", doc
    if doc.status in ("voided", "reversed") or (doc.status == "posted" and doc.void_reason):
        return "duplicate", doc
    doc.void_reason = reason
    if doc.status == "held":
        doc.status, doc.problem, doc.updated_at = "voided", None, utcnow()
        return "voided", doc
    _reverse(s, doc)
    return ("reversed" if doc.status == "reversed" else "held"), doc


def _numbers(s: Session, doc: IntegrationDocument) -> dict[str, Any]:
    def number(vid: uuid.UUID | None) -> int | None:
        v = s.get(Voucher, vid) if vid else None
        return v.number if v else None

    return {
        "document_status": doc.status,
        "voucher_number": number(doc.voucher_id),
        "reversal_voucher_number": number(doc.reversal_voucher_id),
        "message": doc.problem,
    }


def receive(s: Session, settings: Settings, d: Delivery) -> Reply:
    """One verified webhook, in the caller's unit of work."""
    seen = s.scalar(
        select(IntegrationEvent).where(
            IntegrationEvent.source == SOURCE, IntegrationEvent.event_id == d.event_id
        )
    )
    if seen is not None:
        prior = s.get(IntegrationDocument, seen.document_id) if seen.document_id else None
        body = {"status": "duplicate", **(_numbers(s, prior) if prior else {})}
        return Reply(202 if prior and prior.problem else 200, body)
    doc: IntegrationDocument | None = None
    message = None
    if d.event in ("settlement.approved", "settlement.voided") and not d.data.get("id"):
        result, message = "ignored", "شناسه‌ی صورت‌وضعیت نیامده است"
    elif d.event == "settlement.approved":
        result, doc = _approved(s, settings, d.data)
    elif d.event == "settlement.voided":
        result, doc = _voided(s, d.data)
    else:
        result = "ignored"  # webhook.ping and events this side does not book
    s.add(
        IntegrationEvent(
            source=SOURCE,
            event_id=d.event_id,
            event_type=d.event[:64],
            occurred_at=d.occurred_at,
            document_id=doc.id if doc else None,
            result=result,
            message=(doc.problem if doc else message),
        )
    )
    s.flush()
    if doc is not None and result in ("posted", "reversed", "held"):
        audit.record(
            s,
            f"integrations.va_{result}",
            user_id=None,
            entity_type="integration_document",
            entity_id=doc.id,
            data={"number": doc.number, "event": d.event, "problem": doc.problem},
        )
    body = {"status": result, **(_numbers(s, doc) if doc else {"message": message})}
    # 202: received and kept, but waiting for the accountant (VA need not send again).
    return Reply(202 if doc is not None and doc.problem else 200, body)


# --- for the accountant ----------------------------------------------------------------


def document_out(s: Session, doc: IntegrationDocument) -> IntegrationDocumentOut:
    n = _numbers(s, doc)
    return IntegrationDocumentOut(
        id=doc.id,
        number=doc.number,
        kind=doc.kind,  # type: ignore[arg-type]
        counterparty_code=doc.counterparty_code,
        counterparty_name=doc.counterparty_name,
        document_date=doc.document_date,
        total=doc.total,
        status=doc.status,  # type: ignore[arg-type]
        problem=doc.problem,
        void_reason=doc.void_reason,
        voucher_id=doc.voucher_id,
        voucher_number=n["voucher_number"],
        reversal_voucher_id=doc.reversal_voucher_id,
        reversal_voucher_number=n["reversal_voucher_number"],
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def list_documents(s: Session, q: DocumentQuery) -> Page[IntegrationDocumentOut]:
    stmt = select(IntegrationDocument)
    if q.status:
        stmt = stmt.where(IntegrationDocument.status == q.status)
    if q.q:
        like = f"%{q.q.strip()}%"
        stmt = stmt.where(
            IntegrationDocument.number.like(like)
            | IntegrationDocument.counterparty_name.like(like)
            | IntegrationDocument.counterparty_code.like(like)
        )
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(IntegrationDocument.created_at.desc()).offset(q.offset).limit(q.page_size)
        )
    )
    return Page(
        items=[document_out(s, d) for d in rows], total=total, page=q.page, page_size=q.page_size
    )


def retry(
    s: Session, settings: Settings, actor: Actor, doc_id: uuid.UUID
) -> IntegrationDocumentOut:
    """After the accountant fixed the cause: post a held statement, or reverse a voided one."""
    doc = s.get(IntegrationDocument, doc_id, with_for_update=True)
    if doc is None:
        raise NotFoundError("سند یافت نشد")
    if doc.status == "held":
        _post(s, settings, doc)
    elif doc.status == "posted" and doc.void_reason:
        _reverse(s, doc)
    else:
        raise DomainError("این سند منتظر رسیدگی نیست", code="nothing_to_retry")
    s.flush()
    audit.record(
        s,
        "integrations.va_retried",
        user_id=actor.user_id,
        entity_type="integration_document",
        entity_id=doc.id,
        data={"number": doc.number, "status": doc.status, "problem": doc.problem},
    )
    return document_out(s, doc)


def status(s: Session, settings: Settings) -> IntegrationStatusOut:
    counts = dict(
        s.execute(
            select(IntegrationDocument.status, func.count()).group_by(IntegrationDocument.status)
        ).all()
    )
    events = list(
        s.execute(
            select(IntegrationEvent, IntegrationDocument.number)
            .outerjoin(IntegrationDocument, IntegrationDocument.id == IntegrationEvent.document_id)
            .order_by(IntegrationEvent.created_at.desc())
            .limit(10)
        ).all()
    )
    return IntegrationStatusOut(
        configured=configured(settings),
        held=counts.get("held", 0),
        posted=counts.get("posted", 0),
        last_event_at=events[0][0].created_at if events else None,
        last_events=[
            IntegrationEventOut(
                event_type=e.event_type,
                result=e.result,
                message=e.message,
                received_at=e.created_at,
                document_number=number,
            )
            for e, number in events
        ],
    )
