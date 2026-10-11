"""Card-reader transactions (hardware/payment-terminal-adapter.md).

No real reader is connected yet: the Bank Mellat device model, PSP and its ECR
protocol are unknown (open-questions Q1), so nothing here claims to talk to one.
Until phase 6 the pilot records the tracking number from the stand-alone reader's
slip (``card_reference`` on the payment). The state machine and the rules below are
exercised with ``MockAdapter``, which is refused outside development and test.

Rules enforced here: timeout → Unknown (never Declined); Unknown is never paid
again without an inquiry; one unresolved attempt per cart; amounts must match.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.sales.models import TerminalTransaction
from app.modules.sales.schemas import (
    TerminalInfoOut,
    TerminalResolveIn,
    TerminalStartIn,
    TerminalTxOut,
)
from app.modules.sales.services.pricing import register_and_warehouse

UNRESOLVED = ("Created", "Pending", "Unknown", "ReconciliationRequired")


@dataclass(frozen=True)
class AdapterResult:
    status: str
    rrn: str | None = None
    trace_no: str | None = None
    masked_pan: str | None = None
    response_code: str | None = None


class PaymentTerminalAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property
    def verified(self) -> bool: ...
    @property
    def simulated(self) -> bool: ...
    @property
    def scenarios(self) -> tuple[str, ...]: ...

    def start_sale(
        self, request_id: uuid.UUID, amount: Decimal, scenario: str | None
    ) -> AdapterResult: ...

    def inquire(self, request_id: uuid.UUID, response_code: str | None) -> AdapterResult: ...


class MockAdapter:
    """Development and test only. The scenario is carried in ``response_code``."""

    adapter_id = "mock"
    label = "کارت‌خوان آزمایشی (Mock)"
    verified = False
    simulated = True
    scenarios = ("approve", "decline", "timeout", "unknown", "inquiry_unavailable")

    def start_sale(
        self, request_id: uuid.UUID, amount: Decimal, scenario: str | None
    ) -> AdapterResult:
        sc = scenario or "approve"
        if sc == "approve":
            return AdapterResult(
                "Approved",
                rrn=str(request_id.int)[:12],
                trace_no=str(request_id.int)[-6:],
                masked_pan="603799******0000",
                response_code="00",
            )
        if sc == "decline":
            return AdapterResult("Declined", response_code="51")
        # No answer from the device: the money may or may not have been taken.
        codes = {"timeout": "M-T", "unknown": "M-U", "inquiry_unavailable": "M-R"}
        if sc not in codes:
            raise DomainError("سناریوی آزمایشی نامعتبر است", code="bad_scenario")
        return AdapterResult("Unknown", response_code=codes[sc])

    def inquire(self, request_id: uuid.UUID, response_code: str | None) -> AdapterResult:
        if response_code == "M-T":  # the device had approved before the link dropped
            return AdapterResult(
                "Approved",
                rrn=str(request_id.int)[:12],
                trace_no=str(request_id.int)[-6:],
                masked_pan="603799******0000",
                response_code="00",
            )
        if response_code == "M-U":
            return AdapterResult("Declined", response_code="05")
        return AdapterResult("ReconciliationRequired", response_code=response_code)


def adapter() -> PaymentTerminalAdapter | None:
    settings: Settings = current_app.config["SETTINGS"]
    if settings.enable_mock_payment_terminal and settings.env != "production":
        return MockAdapter()
    return None


def info() -> TerminalInfoOut | None:
    a = adapter()
    if a is None:
        return None
    return TerminalInfoOut(
        adapter_id=a.adapter_id,
        label=a.label,
        verified=a.verified,
        simulated=a.simulated,
        scenarios=list(a.scenarios),
    )


def tx_out(t: TerminalTransaction) -> TerminalTxOut:
    return TerminalTxOut(
        id=t.id,
        request_id=t.request_id,
        cash_register_id=t.cash_register_id,
        cart_id=t.cart_id,
        adapter_id=t.adapter_id,
        amount=t.amount,
        status=t.status,  # type: ignore[arg-type]
        rrn=t.rrn,
        trace_no=t.trace_no,
        masked_pan=t.masked_pan,
        response_code=t.response_code,
        is_simulated=t.is_simulated,
        created_at=t.created_at,
        row_version=version_to_str(t.row_version),
    )


def _apply(t: TerminalTransaction, r: AdapterResult) -> None:
    t.status = r.status
    t.rrn, t.trace_no, t.masked_pan = (
        r.rrn or t.rrn,
        r.trace_no or t.trace_no,
        r.masked_pan or t.masked_pan,
    )
    t.response_code = r.response_code
    t.updated_at = utcnow()


def _audit(s: Session, actor: Actor, t: TerminalTransaction, action: str) -> None:
    # Never card data: status, amount and references only.
    audit.record(
        s,
        f"payments.{action}",
        user_id=actor.user_id,
        entity_type="terminal_transaction",
        entity_id=t.id,
        data={
            "status": t.status,
            "amount": str(t.amount),
            "rrn": t.rrn,
            "simulated": t.is_simulated,
        },
    )


def start(s: Session, actor: Actor, data: TerminalStartIn) -> TerminalTxOut:
    a = adapter()
    if a is None:
        raise DomainError(
            "کارت‌خوان متصل نیست؛ پرداخت را روی دستگاه انجام دهید و شماره پیگیری را وارد کنید",
            code="terminal_not_configured",
        )
    reg, _ = register_and_warehouse(s, data.cash_register_id, actor.branch_ids)
    busy = s.scalar(
        select(TerminalTransaction).where(
            TerminalTransaction.cart_id == data.cart_id,
            TerminalTransaction.status.in_(UNRESOLVED),
        )
    )
    if busy is not None:
        raise ConflictError(
            "تراکنش قبلی این فاکتور نامشخص است؛ ابتدا استعلام کنید", code="terminal_tx_unresolved"
        )
    t = TerminalTransaction(
        request_id=uuid.uuid4(),
        cash_register_id=reg.id,
        cart_id=data.cart_id,
        adapter_id=a.adapter_id,
        amount=data.amount,
        status="Created",
        is_simulated=a.simulated,
        created_by=actor.user_id,
    )
    s.add(t)
    s.flush()
    t.status = "Pending"
    _apply(t, a.start_sale(t.request_id, t.amount, data.scenario))
    s.flush()
    _audit(s, actor, t, "card_attempt")
    s.refresh(t)
    return tx_out(t)


def _get(s: Session, actor: Actor, tx_id: uuid.UUID) -> TerminalTransaction:
    t = s.get(TerminalTransaction, tx_id, with_for_update=True)
    if t is None:
        raise NotFoundError("تراکنش یافت نشد")
    register_and_warehouse(s, t.cash_register_id, actor.branch_ids)
    return t


def get(s: Session, actor: Actor, tx_id: uuid.UUID) -> TerminalTxOut:
    return tx_out(_get(s, actor, tx_id))


def inquire(s: Session, actor: Actor, tx_id: uuid.UUID) -> TerminalTxOut:
    t = _get(s, actor, tx_id)
    if t.status not in ("Unknown", "Pending"):
        return tx_out(t)
    a = adapter()
    if a is None or a.adapter_id != t.adapter_id:
        t.status = "ReconciliationRequired"
    else:
        _apply(t, a.inquire(t.request_id, t.response_code))
    s.flush()
    _audit(s, actor, t, "card_inquiry")
    s.refresh(t)
    return tx_out(t)


def resolve(
    s: Session, actor: Actor, tx_id: uuid.UUID, data: TerminalResolveIn, version: str
) -> TerminalTxOut:
    """Manual reconciliation against the PSP report (payments.reconcile)."""
    t = _get(s, actor, tx_id)
    check_version(t.row_version, version, "این تراکنش")
    if t.status not in ("Unknown", "ReconciliationRequired"):
        raise ConflictError("فقط تراکنش نامشخص قابل تطبیق است", code="not_reconcilable")
    if data.status == "Approved" and not data.rrn:
        raise DomainError(
            "برای تأیید، شماره مرجع (RRN) از گزارش بانک لازم است", code="rrn_required"
        )
    t.status, t.rrn = data.status, data.rrn or t.rrn
    t.resolved_by, t.resolution_note, t.updated_at = actor.user_id, data.note, utcnow()
    s.flush()
    _audit(s, actor, t, "card_reconciled")
    s.refresh(t)
    return tx_out(t)


def list_unresolved(s: Session, actor: Actor) -> list[TerminalTxOut]:
    rows = list(
        s.scalars(
            select(TerminalTransaction)
            .where(TerminalTransaction.status.in_(UNRESOLVED))
            .order_by(TerminalTransaction.created_at)
        )
    )
    out = []
    for t in rows:
        try:
            register_and_warehouse(s, t.cash_register_id, actor.branch_ids)
        except (NotFoundError, DomainError):
            continue
        out.append(tx_out(t))
    return out


def use_for_payment(
    s: Session, tx_id: uuid.UUID, *, register_id: uuid.UUID, amount: Decimal, cart_id: uuid.UUID
) -> TerminalTransaction:
    """Checks before a card payment may rely on a transaction (rule 2 and 5)."""
    t = s.get(TerminalTransaction, tx_id, with_for_update=True)
    if t is None or t.cash_register_id != register_id or t.cart_id != cart_id:
        raise DomainError("تراکنش کارت‌خوان با این فاکتور مطابقت ندارد", code="terminal_tx_mismatch")
    if t.status != "Approved":
        raise DomainError("تراکنش کارت‌خوان تأیید نشده است", code="terminal_tx_not_approved")
    if t.amount != amount:
        raise DomainError(
            "مبلغ تراکنش کارت‌خوان با مبلغ پرداخت برابر نیست", code="terminal_amount_mismatch"
        )
    settings: Settings = current_app.config["SETTINGS"]
    if t.is_simulated and settings.env == "production":
        raise DomainError(
            "تراکنش آزمایشی در محیط عملیاتی پذیرفته نمی‌شود", code="simulated_in_production"
        )
    return t
