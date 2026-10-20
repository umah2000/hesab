"""Automatic vouchers from business events via posting rules (posting-rules.md).

Callers (sales, purchasing, inventory…) describe *what happened* as amounts per
line role; the accounts come from the configurable ``posting_rule`` table.
The voucher is created and finalised inside the caller's unit of work, so the
business document and its voucher commit or roll back together.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import DomainError
from app.core.money import ZERO
from app.modules.accounting.defaults import EVENTS, EVENTS_BY_TYPE
from app.modules.accounting.models import Account, PostingRule, Voucher
from app.modules.accounting.schemas import PostingRuleIn, PostingRuleOut
from app.modules.accounting.services.vouchers import LineSpec, build_draft, finalize_voucher
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor


@dataclass(frozen=True)
class Entry:
    role: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    detail_account_id: uuid.UUID | None = None
    description: str | None = None


def post_event(
    s: Session,
    *,
    event_type: str,
    document_date: date,
    branch_id: uuid.UUID | None,
    entries: list[Entry],
    actor_id: uuid.UUID | None,
    source_ref: str | None = None,
    source_id: uuid.UUID | None = None,
    description: str | None = None,
    draft: bool = False,
) -> Voucher:
    """Build the voucher from posting rules and finalise it (``draft=True``: leave it a
    draft for an accountant to review, e.g. imported opening balances)."""
    event = EVENTS_BY_TYPE.get(event_type)
    if event is None:
        raise ValueError(f"unknown posting event {event_type!r}")
    known_roles = {r.role for r in event.roles}
    rules = {
        r.line_role: r.account_id
        for r in s.scalars(select(PostingRule).where(PostingRule.event_type == event_type))
    }
    lines: list[LineSpec] = []
    for e in entries:
        if e.role not in known_roles:
            raise ValueError(f"role {e.role!r} is not defined for {event_type}")
        if e.debit == 0 and e.credit == 0:
            continue
        account_id = rules.get(e.role)
        if account_id is None:
            label = next(r.label for r in event.roles if r.role == e.role)
            raise DomainError(
                f"قاعده ثبت «{event.label} / {label}» تعریف نشده است", code="posting_rule_missing"
            )
        lines.append(
            LineSpec(
                account_id=account_id,
                debit=e.debit,
                credit=e.credit,
                detail_account_id=e.detail_account_id,
                description=e.description,
            )
        )
    v = build_draft(
        s,
        actor_id=actor_id,
        branch_id=branch_id,
        document_date=document_date,
        description=description or event.label,
        lines=lines,
        source_type="auto",
        source_ref=event_type,
        source_id=source_id,
    )
    return v if draft else finalize_voucher(s, v, actor_id)


def list_rules(s: Session) -> list[PostingRuleOut]:
    rules = {(r.event_type, r.line_role): r.account_id for r in s.scalars(select(PostingRule))}
    accounts = (
        {a.id: a for a in s.scalars(select(Account).where(Account.id.in_(set(rules.values()))))}
        if rules
        else {}
    )
    out = []
    for ev in EVENTS:
        for role in ev.roles:
            acc = accounts.get(rules.get((ev.event_type, role.role)))  # type: ignore[arg-type]
            out.append(
                PostingRuleOut(
                    event_type=ev.event_type,
                    event_label=ev.label,
                    line_role=role.role,
                    role_label=role.label,
                    account_id=acc.id if acc else None,
                    account_code=acc.code if acc else None,
                    account_name=acc.name if acc else None,
                )
            )
    return out


def set_rule(s: Session, actor: Actor, data: PostingRuleIn) -> list[PostingRuleOut]:
    event = EVENTS_BY_TYPE.get(data.event_type)
    if event is None or data.line_role not in {r.role for r in event.roles}:
        raise DomainError("رویداد یا نقش ردیف نامعتبر است", code="invalid_rule")
    acc = s.get(Account, data.account_id)
    if acc is None or acc.level != "subsidiary" or not acc.is_active:
        raise DomainError("فقط حساب معین فعال قابل انتخاب است", code="account_not_postable")
    rule = s.scalar(
        select(PostingRule).where(
            PostingRule.event_type == data.event_type, PostingRule.line_role == data.line_role
        )
    )
    before = str(rule.account_id) if rule else None
    if rule is None:
        rule = PostingRule(
            event_type=data.event_type,
            line_role=data.line_role,
            account_id=acc.id,
            created_by=actor.user_id,
        )
        s.add(rule)
    else:
        rule.account_id = acc.id
        rule.updated_at = utcnow()
    rule.updated_by = actor.user_id
    s.flush()
    audit.record(
        s,
        "accounting.posting_rule_set",
        user_id=actor.user_id,
        entity_type="posting_rule",
        entity_id=rule.id,
        data={
            "event": data.event_type,
            "role": data.line_role,
            "before": before,
            "after": acc.code,
        },
    )
    return list_rules(s)
