"""Counterparties: CRUD, balances, statement (گردش حساب), notes and follow-ups."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.http import Page
from app.modules.accounting.models import Account, DetailAccount, Voucher, VoucherLine
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.parties.models import Party, PartyGroup, PartyNote
from app.modules.parties.schemas import (
    GroupIn,
    GroupOut,
    NoteIn,
    NoteOut,
    PartyCreateIn,
    PartyFields,
    PartyOut,
    PartyQuery,
    PartySummary,
    PartyUpdateIn,
    StatementLine,
    StatementOut,
)

ZERO = Decimal(0)
SENSITIVE = (
    "national_id",
    "economic_code",
    "registration_no",
    "phone",
    "mobile",
    "email",
    "postal_code",
    "address",
)
FIELDS = (
    "party_type",
    "is_customer",
    "is_supplier",
    "group_id",
    "national_id",
    "economic_code",
    "registration_no",
    "phone",
    "mobile",
    "email",
    "postal_code",
    "city",
    "address",
    "payment_terms_days",
)


def mask(v: str | None) -> str | None:
    if not v:
        return v
    if len(v) <= 4:
        return "•" * len(v)
    return v[:2] + "•" * (len(v) - 4) + v[-2:]


def balances(s: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Debit − credit over all final vouchers: positive = the party owes us."""
    if not ids:
        return {}
    rows = s.execute(
        select(VoucherLine.detail_account_id, func.sum(VoucherLine.debit - VoucherLine.credit))
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(Voucher.status == "final", VoucherLine.detail_account_id.in_(ids))
        .group_by(VoucherLine.detail_account_id)
    ).all()
    return {k: Decimal(v or 0) for k, v in rows if k is not None}


def _get(s: Session, party_id: uuid.UUID) -> tuple[Party, DetailAccount]:
    p = s.get(Party, party_id)
    d = s.get(DetailAccount, party_id)
    if p is None or d is None:
        raise NotFoundError("طرف‌حساب یافت نشد")
    return p, d


def party_out(s: Session, actor: Actor, p: Party, d: DetailAccount) -> PartyOut:
    group = s.get(PartyGroup, p.group_id) if p.group_id else None
    masked = not actor.has("parties.manage")
    vals = {f: getattr(p, f) for f in FIELDS}
    if masked:
        for f in SENSITIVE:
            vals[f] = mask(vals[f])
    return PartyOut(
        id=p.id,
        code=d.code,
        name=d.name,
        group_name=group.name if group else None,
        credit_limit=d.credit_limit,
        balance=balances(s, [p.id]).get(p.id, ZERO),
        is_active=d.is_active,
        masked=masked,
        created_at=p.created_at,
        row_version=version_to_str(p.row_version),
        **vals,
    )


def apply_fields(p: Party, d: DetailAccount, data: PartyFields) -> None:
    for f in FIELDS:
        setattr(p, f, getattr(data, f))
    d.name = data.name
    d.credit_limit = data.credit_limit if data.is_customer else None


def _check_group(s: Session, group_id: uuid.UUID | None) -> None:
    if group_id is not None and s.get(PartyGroup, group_id) is None:
        raise NotFoundError("گروه طرف‌حساب یافت نشد")


def create(s: Session, actor: Actor, data: PartyCreateIn) -> PartyOut:
    if s.scalar(select(DetailAccount.id).where(DetailAccount.code == data.code)):
        raise ConflictError("کد طرف‌حساب (تفصیلی) تکراری است", code="party_code_taken")
    _check_group(s, data.group_id)
    d = DetailAccount(
        code=data.code,
        name=data.name,
        kind="person",
        is_active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(d)
    s.flush()
    p = Party(id=d.id, created_by=actor.user_id, updated_by=actor.user_id)
    apply_fields(p, d, data)
    s.add(p)
    try:
        s.flush()
    except IntegrityError as e:
        raise ConflictError(
            "این کد/شناسه ملی برای طرف‌حساب دیگری ثبت شده است", code="national_id_taken"
        ) from e
    audit.record(
        s,
        "parties.created",
        user_id=actor.user_id,
        entity_type="party",
        entity_id=p.id,
        data={"code": d.code},
    )
    s.refresh(p)
    return party_out(s, actor, p, d)


def update(
    s: Session, actor: Actor, party_id: uuid.UUID, data: PartyUpdateIn, version: str
) -> PartyOut:
    p, d = _get(s, party_id)
    check_version(p.row_version, version, "این طرف‌حساب")
    _check_group(s, data.group_id)
    before = {
        "credit_limit": str(d.credit_limit) if d.credit_limit is not None else None,
        "is_active": d.is_active,
    }
    apply_fields(p, d, data)
    d.is_active = data.is_active
    p.updated_by = d.updated_by = actor.user_id
    p.updated_at = d.updated_at = utcnow()
    try:
        s.flush()
    except IntegrityError as e:
        raise ConflictError(
            "این کد/شناسه ملی برای طرف‌حساب دیگری ثبت شده است", code="national_id_taken"
        ) from e
    audit.record(
        s,
        "parties.updated",
        user_id=actor.user_id,
        entity_type="party",
        entity_id=p.id,
        data={
            "before": before,
            "credit_limit": str(d.credit_limit) if d.credit_limit is not None else None,
        },
    )
    s.refresh(p)
    return party_out(s, actor, p, d)


def get(s: Session, actor: Actor, party_id: uuid.UUID) -> PartyOut:
    p, d = _get(s, party_id)
    return party_out(s, actor, p, d)


def list_parties(s: Session, actor: Actor, q: PartyQuery) -> Page[PartySummary]:
    stmt = select(Party, DetailAccount).join(DetailAccount, DetailAccount.id == Party.id)
    if q.q:
        term = q.q.strip()
        stmt = stmt.where(
            or_(
                DetailAccount.name.contains(term),
                DetailAccount.code.contains(term),
                Party.mobile.contains(term),
                Party.national_id == term,
            )
        )
    if q.role == "customer":
        stmt = stmt.where(Party.is_customer == true())
    elif q.role == "supplier":
        stmt = stmt.where(Party.is_supplier == true())
    if q.group_id:
        stmt = stmt.where(Party.group_id == q.group_id)
    if q.active is not None:
        stmt = stmt.where(DetailAccount.is_active == q.active)
    if q.balance:
        bal = (
            select(VoucherLine.detail_account_id)
            .join(Voucher, Voucher.id == VoucherLine.voucher_id)
            .where(Voucher.status == "final")
            .group_by(VoucherLine.detail_account_id)
            .having(
                func.sum(VoucherLine.debit - VoucherLine.credit) > 0
                if q.balance == "debtor"
                else func.sum(VoucherLine.debit - VoucherLine.credit) < 0
            )
        )
        stmt = stmt.where(Party.id.in_(bal))
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.execute(
            stmt.order_by(DetailAccount.name).offset((q.page - 1) * q.page_size).limit(q.page_size)
        ).all()
    )
    bals = balances(s, [p.id for p, _ in rows])
    groups = {g.id: g.name for g in s.scalars(select(PartyGroup))}
    masked = not actor.has("parties.manage")
    return Page(
        items=[
            PartySummary(
                id=p.id,
                code=d.code,
                name=d.name,
                party_type=p.party_type,  # type: ignore[arg-type]
                is_customer=p.is_customer,
                is_supplier=p.is_supplier,
                group_name=groups.get(p.group_id) if p.group_id else None,
                mobile=mask(p.mobile) if masked else p.mobile,
                credit_limit=d.credit_limit,
                balance=bals.get(p.id, ZERO),
                is_active=d.is_active,
            )
            for p, d in rows
        ],
        total=int(total),
        page=q.page,
        page_size=q.page_size,
    )


def statement(
    s: Session, party_id: uuid.UUID, date_from: date | None, date_to: date | None
) -> StatementOut:
    _, d = _get(s, party_id)
    base = (
        select(VoucherLine, Voucher, Account)
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .join(Account, Account.id == VoucherLine.account_id)
        .where(Voucher.status == "final", VoucherLine.detail_account_id == party_id)
    )
    opening = ZERO
    if date_from:
        opening = Decimal(
            s.scalar(
                select(func.sum(VoucherLine.debit - VoucherLine.credit))
                .join(Voucher, Voucher.id == VoucherLine.voucher_id)
                .where(
                    Voucher.status == "final",
                    VoucherLine.detail_account_id == party_id,
                    Voucher.document_date < date_from,
                )
            )
            or 0
        )
        base = base.where(Voucher.document_date >= date_from)
    if date_to:
        base = base.where(Voucher.document_date <= date_to)
    rows = list(
        s.execute(base.order_by(Voucher.document_date, Voucher.number, VoucherLine.line_no)).all()
    )
    running = opening
    lines: list[StatementLine] = []
    td = tc = ZERO
    for ln, v, acc in rows:
        running += ln.debit - ln.credit
        td += ln.debit
        tc += ln.credit
        lines.append(
            StatementLine(
                voucher_id=v.id,
                voucher_number=v.number,
                document_date=v.document_date,
                description=ln.description or v.description,
                account_code=acc.code,
                account_name=acc.name,
                debit=ln.debit,
                credit=ln.credit,
                balance=running,
            )
        )
    return StatementOut(
        party_id=party_id,
        party_name=d.name,
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        total_debit=td,
        total_credit=tc,
        closing_balance=running,
        lines=lines,
    )


# --- notes / follow-ups ---------------------------------------------------------


def _note_out(s: Session, n: PartyNote) -> NoteOut:
    d = s.get(DetailAccount, n.party_id)
    u = s.get(AppUser, n.created_by) if n.created_by else None
    return NoteOut(
        id=n.id,
        party_id=n.party_id,
        party_name=d.name if d else "",
        body=n.body,
        follow_up_on=n.follow_up_on,
        done=n.done,
        author=(u.full_name or u.username) if u else "",
        created_at=n.created_at,
    )


def add_note(s: Session, actor: Actor, party_id: uuid.UUID, data: NoteIn) -> NoteOut:
    _get(s, party_id)
    n = PartyNote(
        party_id=party_id,
        body=data.body,
        follow_up_on=data.follow_up_on,
        done=False,
        created_by=actor.user_id,
    )
    s.add(n)
    s.flush()
    s.refresh(n)
    return _note_out(s, n)


def notes(s: Session, party_id: uuid.UUID) -> list[NoteOut]:
    rows = list(
        s.scalars(
            select(PartyNote)
            .where(PartyNote.party_id == party_id)
            .order_by(PartyNote.created_at.desc())
        )
    )
    return [_note_out(s, n) for n in rows]


def set_note_done(s: Session, note_id: uuid.UUID, done: bool) -> NoteOut:
    n = s.get(PartyNote, note_id)
    if n is None:
        raise NotFoundError("یادداشت یافت نشد")
    n.done = done
    s.flush()
    return _note_out(s, n)


def due_follow_ups(s: Session, until: date) -> list[NoteOut]:
    rows = list(
        s.scalars(
            select(PartyNote)
            .where(PartyNote.done == False, PartyNote.follow_up_on <= until)  # noqa: E712
            .order_by(PartyNote.follow_up_on)
            .limit(200)
        )
    )
    return [_note_out(s, n) for n in rows]


# --- groups ------------------------------------------------------------------------


def list_groups(s: Session) -> list[GroupOut]:
    return [
        GroupOut(id=g.id, code=g.code, name=g.name)
        for g in s.scalars(select(PartyGroup).order_by(PartyGroup.name))
    ]


def create_group(s: Session, actor: Actor, data: GroupIn) -> GroupOut:
    if s.scalar(select(PartyGroup.id).where(PartyGroup.code == data.code)):
        raise ConflictError("کد گروه تکراری است", code="group_code_taken")
    g = PartyGroup(
        code=data.code, name=data.name, created_by=actor.user_id, updated_by=actor.user_id
    )
    s.add(g)
    s.flush()
    return GroupOut(id=g.id, code=g.code, name=g.name)


def ensure_party(s: Session, detail_id: uuid.UUID, *, supplier: bool = False) -> Party:
    """A person detail account used before phase 5 gets its party row on first use."""
    p = s.get(Party, detail_id)
    d = s.get(DetailAccount, detail_id)
    if d is None or d.kind != "person":
        raise NotFoundError("طرف‌حساب یافت نشد")
    if p is None:
        p = Party(id=d.id, party_type="person", is_customer=not supplier, is_supplier=supplier)
        s.add(p)
        s.flush()
    return p


def require_supplier(s: Session, party_id: uuid.UUID) -> tuple[Party, DetailAccount]:
    p, d = _get(s, party_id)
    if not p.is_supplier or not d.is_active:
        raise DomainError("طرف‌حساب انتخاب‌شده تأمین‌کننده فعال نیست", code="not_a_supplier")
    return p, d
