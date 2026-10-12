"""Cheque lifecycle (چک دریافتی / پرداختی) with an append-only history.

Received: in_hand → deposited → cleared | bounced; in_hand → cleared (cashed);
in_hand | bounced → returned (handed back); bounced → deposited (redeposit).
Issued:   issued → cleared | bounced | cancelled.

Each step that moves money posts ``treasury.cheque.changed``; the party side
(receivable or payable) is the one the original receipt or payment used.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import version_to_str
from app.core.errors import DomainError, NotFoundError
from app.core.http import Page
from app.modules.accounting.models import DetailAccount
from app.modules.accounting.services.chart import check_version
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.treasury.models import Cheque, ChequeEvent, MoneyAccount, TreasuryDocument
from app.modules.treasury.schemas import (
    ChequeActionIn,
    ChequeEventOut,
    ChequeOut,
    ChequeQuery,
    ChequeSummary,
)
from app.modules.treasury.services import accounts

ZERO = Decimal(0)
OPEN = ("in_hand", "deposited", "issued")


@dataclass(frozen=True)
class Step:
    to: str
    # Needs a money account chosen now (deposit, cashing a cheque in hand).
    needs_account: bool = False


TRANSITIONS: dict[tuple[str, str], dict[str, Step]] = {
    ("received", "in_hand"): {
        "deposit": Step("deposited", needs_account=True),
        "clear": Step("cleared", needs_account=True),
        "return": Step("returned"),
    },
    ("received", "deposited"): {"clear": Step("cleared"), "bounce": Step("bounced")},
    ("received", "bounced"): {
        "redeposit": Step("deposited", needs_account=True),
        "return": Step("returned"),
    },
    ("issued", "issued"): {
        "clear": Step("cleared"),
        "bounce": Step("bounced"),
        "cancel": Step("cancelled"),
    },
}
LABELS = {
    "deposit": "واگذاری به بانک",
    "clear": "وصول",
    "bounce": "برگشت (عدم وصول)",
    "return": "استرداد به صاحب چک",
    "redeposit": "واگذاری مجدد",
    "cancel": "ابطال چک پرداختی",
}


def actions(c: Cheque) -> list[str]:
    return list(TRANSITIONS.get((c.direction, c.status), {}))


def cheque_out(s: Session, c: Cheque) -> ChequeOut:
    names = {
        k: v
        for k, v in s.execute(
            select(DetailAccount.id, DetailAccount.name).where(
                DetailAccount.id.in_(
                    {c.party_id, c.money_account_id}
                    | {e.money_account_id for e in c.events if e.money_account_id} - {None}
                )
            )
        )
    }
    users = {
        k: v
        for k, v in s.execute(
            select(AppUser.id, AppUser.full_name).where(
                AppUser.id.in_({e.created_by for e in c.events if e.created_by})
            )
        )
    }
    doc = s.get(TreasuryDocument, c.document_id)
    return ChequeOut(
        id=c.id,
        direction=c.direction,
        status=c.status,
        party_id=c.party_id,
        party_name=names.get(c.party_id, ""),
        number=c.number,
        sayad_id=c.sayad_id,
        bank_name=c.bank_name,
        drawer=c.drawer,
        amount=c.amount,
        due_date=c.due_date,
        money_account_id=c.money_account_id,
        money_account_name=names.get(c.money_account_id) if c.money_account_id else None,
        document_id=c.document_id,
        document_number=doc.number if doc else None,
        actions=actions(c),
        events=[
            ChequeEventOut(
                seq=e.seq,
                event_date=e.event_date,
                from_status=e.from_status,
                to_status=e.to_status,
                money_account_name=names.get(e.money_account_id) if e.money_account_id else None,
                voucher_id=e.voucher_id,
                note=e.note,
                user=users.get(e.created_by) if e.created_by else None,
                created_at=e.created_at,
            )
            for e in c.events
        ],
        row_version=version_to_str(c.row_version),
    )


def _get(s: Session, actor: Actor, cheque_id: uuid.UUID, lock: bool = False) -> Cheque:
    c = s.get(Cheque, cheque_id, with_for_update=lock)
    if c is None or not actor.can_access_branch(c.branch_id):
        raise NotFoundError("چک یافت نشد")
    return c


def get(s: Session, actor: Actor, cheque_id: uuid.UUID) -> ChequeOut:
    return cheque_out(s, _get(s, actor, cheque_id))


def _entries(c: Cheque, action: str, side: str, account: MoneyAccount | None) -> list[Entry]:
    p, amt = c.party_id, c.amount
    if c.direction == "received":
        if action == "clear":
            assert account is not None
            return [
                Entry(account.kind, debit=amt, detail_account_id=account.id),
                Entry("cheques_receivable", credit=amt, detail_account_id=p),
            ]
        if action == "bounce" or (action == "return" and c.status == "in_hand"):
            return [
                Entry(side, debit=amt, detail_account_id=p),
                Entry("cheques_receivable", credit=amt, detail_account_id=p),
            ]
        if action == "redeposit":
            return [
                Entry("cheques_receivable", debit=amt, detail_account_id=p),
                Entry(side, credit=amt, detail_account_id=p),
            ]
        return []  # deposit, handing back a bounced cheque: no money moves
    if action == "clear":
        assert account is not None
        return [
            Entry("cheques_payable", debit=amt, detail_account_id=p),
            Entry("bank", credit=amt, detail_account_id=account.id),
        ]
    return [  # bounced or cancelled: the debt to the party is back
        Entry("cheques_payable", debit=amt, detail_account_id=p),
        Entry(side, credit=amt, detail_account_id=p),
    ]


def act(
    s: Session, actor: Actor, cheque_id: uuid.UUID, data: ChequeActionIn, version: str
) -> ChequeOut:
    c = _get(s, actor, cheque_id, lock=True)
    check_version(c.row_version, version, "این چک")
    step = TRANSITIONS.get((c.direction, c.status), {}).get(data.action)
    if step is None:
        raise DomainError(
            f"«{LABELS[data.action]}» برای چک در این وضعیت مجاز نیست", code="bad_cheque_action"
        )
    last = c.events[-1].event_date if c.events else None
    if last and data.event_date < last:
        raise DomainError("تاریخ رویداد پیش از آخرین رویداد چک است", code="bad_dates")

    account: MoneyAccount | None = None
    if step.needs_account:
        if data.money_account_id is None:
            raise DomainError("حساب بانکی را انتخاب کنید", code="account_required")
        # Deposits go to a bank; a cheque in hand may also be cashed into a box.
        kind = "bank" if data.action in ("deposit", "redeposit") else None
        m, _ = accounts.require(s, actor, data.money_account_id, kind)
        if m.kind == "cash" and m.branch_id != c.branch_id:
            raise DomainError("صندوق متعلق به شعبه این چک نیست", code="other_branch_cash")
        account = m
        c.money_account_id = m.id
    elif c.money_account_id is not None:
        account = s.get(MoneyAccount, c.money_account_id)

    doc = s.get(TreasuryDocument, c.document_id)
    assert doc is not None
    side = doc.against or ("receivable" if c.direction == "received" else "payable")
    entries = _entries(c, data.action, side, account)
    voucher_id = None
    if entries:
        party = s.get(DetailAccount, c.party_id)
        v = post_event(
            s,
            event_type="treasury.cheque.changed",
            document_date=data.event_date,
            branch_id=c.branch_id,
            entries=entries,
            actor_id=actor.user_id,
            source_id=c.id,
            description=f"{LABELS[data.action]} چک {c.number} — {party.name if party else ''}",
        )
        voucher_id = v.id
    s.add(
        ChequeEvent(
            cheque_id=c.id,
            seq=len(c.events) + 1,
            event_date=data.event_date,
            from_status=c.status,
            to_status=step.to,
            money_account_id=account.id if account else None,
            voucher_id=voucher_id,
            note=data.note,
            created_by=actor.user_id,
        )
    )
    old = c.status
    c.status, c.updated_by = step.to, actor.user_id
    s.flush()
    s.expire(c, ["events"])
    audit.record(
        s,
        "treasury.cheque_changed",
        user_id=actor.user_id,
        branch_id=c.branch_id,
        entity_type="cheque",
        entity_id=c.id,
        data={"from": old, "to": step.to, "number": c.number},
    )
    return cheque_out(s, c)


def list_cheques(s: Session, actor: Actor, q: ChequeQuery, today: date) -> Page[ChequeSummary]:
    stmt = select(Cheque)
    if actor.branch_ids is not None:
        stmt = stmt.where(Cheque.branch_id.in_(actor.branch_ids))
    if q.direction:
        stmt = stmt.where(Cheque.direction == q.direction)
    if q.status:
        stmt = stmt.where(Cheque.status == q.status)
    if q.due_until:
        stmt = stmt.where(Cheque.due_date <= q.due_until, Cheque.status.in_(OPEN))
    if q.party_id:
        stmt = stmt.where(Cheque.party_id == q.party_id)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(Cheque.due_date, Cheque.number)
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    names = {
        k: v
        for k, v in s.execute(
            select(DetailAccount.id, DetailAccount.name).where(
                DetailAccount.id.in_({r.party_id for r in rows} or {uuid.UUID(int=0)})
            )
        )
    }
    return Page(
        items=[
            ChequeSummary(
                id=r.id,
                direction=r.direction,
                status=r.status,
                party_name=names.get(r.party_id, ""),
                number=r.number,
                bank_name=r.bank_name,
                amount=r.amount,
                due_date=r.due_date,
                overdue=r.status in OPEN and r.due_date < today,
            )
            for r in rows
        ],
        total=total,
        page=q.page,
        page_size=q.page_size,
    )
