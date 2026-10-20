"""Receipts, payments, transfers and card-reader settlements.

Each document is written as a draft, its voucher is posted from rules, then it is
flipped to final in the same unit of work. Corrections are reversals: a mirror voucher,
the document marked ``reversed`` and its cheques voided — never an edit.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import DomainError, NotFoundError
from app.core.http import Page
from app.core.numbering import next_number
from app.modules.accounting.models import DetailAccount, Voucher
from app.modules.accounting.services import vouchers
from app.modules.accounting.services.chart import check_version
from app.modules.accounting.services.fiscal import open_year_for
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.organization.models import Branch
from app.modules.parties.models import Party
from app.modules.treasury.models import (
    Cheque,
    ChequeEvent,
    MoneyAccount,
    TreasuryDocument,
    TreasuryLine,
)
from app.modules.treasury.schemas import (
    DocumentOut,
    DocumentQuery,
    DocumentSummary,
    LineOut,
    ReceiptIn,
    ReverseIn,
    SettlementIn,
    TransferIn,
)
from app.modules.treasury.services import accounts

ZERO = Decimal(0)
LABELS = {
    "receipt": "دریافت",
    "payment": "پرداخت",
    "transfer": "انتقال وجه",
    "settlement": "تسویه کارت‌خوان",
}
EVENTS = {
    "receipt": "treasury.receipt.finalized",
    "payment": "treasury.payment.finalized",
    "transfer": "treasury.transfer.finalized",
    "settlement": "payments.card.settled",
}


# --- output -----------------------------------------------------------------


def _names(s: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    real = {i for i in ids if i is not None}
    if not real:
        return {}
    return {
        k: v
        for k, v in s.execute(
            select(DetailAccount.id, DetailAccount.name).where(DetailAccount.id.in_(real))
        )
    }


def document_out(s: Session, doc: TreasuryDocument) -> DocumentOut:
    cheques = {
        c.id: c
        for c in s.scalars(
            select(Cheque).where(Cheque.id.in_({ln.cheque_id for ln in doc.lines if ln.cheque_id}))
        )
    }
    names = _names(
        s,
        {doc.party_id, doc.from_account_id, doc.to_account_id}
        | {ln.money_account_id for ln in doc.lines},
    )
    return DocumentOut(
        id=doc.id,
        kind=doc.kind,
        status=doc.status,
        number=doc.number,
        branch_id=doc.branch_id,
        document_date=doc.document_date,
        party_id=doc.party_id,
        party_name=names.get(doc.party_id) if doc.party_id else None,
        against=doc.against,
        from_account_id=doc.from_account_id,
        from_account_name=names.get(doc.from_account_id) if doc.from_account_id else None,
        to_account_id=doc.to_account_id,
        to_account_name=names.get(doc.to_account_id) if doc.to_account_id else None,
        amount=doc.amount,
        fee=doc.fee,
        reference=doc.reference,
        description=doc.description,
        voucher_id=doc.voucher_id,
        reversal_voucher_id=doc.reversal_voucher_id,
        reversed_at=doc.reversed_at,
        reversal_reason=doc.reversal_reason,
        lines=[
            LineOut(
                line_no=ln.line_no,
                method=ln.method,
                money_account_id=ln.money_account_id,
                money_account_name=names.get(ln.money_account_id) if ln.money_account_id else None,
                amount=ln.amount,
                reference=ln.reference,
                cheque_id=ln.cheque_id,
                cheque_number=cheques[ln.cheque_id].number if ln.cheque_id else None,
                cheque_due_date=cheques[ln.cheque_id].due_date if ln.cheque_id else None,
                cheque_status=cheques[ln.cheque_id].status if ln.cheque_id else None,
            )
            for ln in doc.lines
        ],
        created_at=doc.created_at,
        row_version=version_to_str(doc.row_version),
    )


# --- helpers ----------------------------------------------------------------


def _branch(s: Session, actor: Actor, branch_id: uuid.UUID) -> Branch:
    b = s.get(Branch, branch_id)
    if b is None or not b.is_active or not actor.can_access_branch(b.id):
        raise NotFoundError("شعبه یافت نشد")
    return b


def _party(s: Session, party_id: uuid.UUID) -> tuple[Party, DetailAccount]:
    p = s.get(Party, party_id)
    d = s.get(DetailAccount, party_id)
    if p is None or d is None:
        raise NotFoundError("طرف‌حساب یافت نشد")
    if not d.is_active:
        raise DomainError(f"طرف‌حساب «{d.name}» غیرفعال است", code="party_inactive")
    return p, d


def _account(
    s: Session, actor: Actor, account_id: uuid.UUID, branch_id: uuid.UUID, kind: str | None = None
) -> tuple[str, DetailAccount]:
    m, d = accounts.require(s, actor, account_id, kind)
    if m.kind == "cash" and m.branch_id != branch_id:
        raise DomainError(f"صندوق «{d.name}» متعلق به این شعبه نیست", code="other_branch_cash")
    return m.kind, d


def _withdraw(s: Session, account_id: uuid.UUID, amount: Decimal) -> None:
    """Cash never goes below zero. The box row is locked (key seek) so two cashiers
    cannot both spend the same money."""
    m = s.get(MoneyAccount, account_id, with_for_update=True)
    if m is None or m.kind != "cash":
        return
    d = s.get(DetailAccount, account_id)
    bal = accounts.balances(s, [account_id]).get(account_id, ZERO)
    if bal < amount:
        raise DomainError(
            f"موجودی «{d.name if d else ''}» کافی نیست (موجود: {bal:f} ریال)",
            code="insufficient_cash",
        )


def _start(
    s: Session, actor: Actor, kind: str, branch_id: uuid.UUID, data_date: date
) -> TreasuryDocument:
    _branch(s, actor, branch_id)
    fy = open_year_for(s, data_date)
    return TreasuryDocument(
        kind=kind,
        status="draft",
        branch_id=branch_id,
        fiscal_year_id=fy.id,
        document_date=data_date,
        fee=ZERO,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )


def _finish(
    s: Session, actor: Actor, doc: TreasuryDocument, entries: list[Entry], what: str
) -> TreasuryDocument:
    doc.number = next_number(s, doc.kind, doc.fiscal_year_id, doc.branch_id)
    v = post_event(
        s,
        event_type=EVENTS[doc.kind],
        document_date=doc.document_date,
        branch_id=doc.branch_id,
        entries=entries,
        actor_id=actor.user_id,
        source_id=doc.id,
        description=f"{LABELS[doc.kind]} شماره {doc.number} — {what}"
        + (f" — {doc.description}" if doc.description else ""),
    )
    doc.voucher_id = v.id
    # A cheque's history starts with the voucher that brought it in (append-only).
    for c in list(s.scalars(select(Cheque).where(Cheque.document_id == doc.id))):
        s.add(
            ChequeEvent(
                cheque_id=c.id,
                seq=1,
                event_date=doc.document_date,
                to_status=c.status,
                money_account_id=c.money_account_id,
                voucher_id=v.id,
                created_by=actor.user_id,
            )
        )
    s.flush()
    doc.status = "final"
    s.flush()
    audit.record(
        s,
        f"treasury.{doc.kind}_created",
        user_id=actor.user_id,
        branch_id=doc.branch_id,
        entity_type="treasury_document",
        entity_id=doc.id,
        data={"number": doc.number, "amount": str(doc.amount)},
    )
    return doc


# --- receipts and payments --------------------------------------------------


def _receipt_or_payment(s: Session, actor: Actor, kind: str, data: ReceiptIn) -> DocumentOut:
    incoming = kind == "receipt"
    doc = _start(s, actor, kind, data.branch_id, data.document_date)
    party, pd = _party(s, data.party_id)
    against = data.against or ("receivable" if party.is_customer else "payable")
    doc.party_id, doc.against, doc.description = party.id, against, data.description
    doc.amount = sum((ln.amount for ln in data.lines), ZERO)
    s.add(doc)
    s.flush()

    entries: list[Entry] = []
    for n, ln in enumerate(data.lines, start=1):
        row = TreasuryLine(line_no=n, method=ln.method, amount=ln.amount, reference=ln.reference)
        if ln.method in ("cash", "bank"):
            assert ln.money_account_id is not None
            akind, _ = _account(s, actor, ln.money_account_id, doc.branch_id, ln.method)
            row.money_account_id = ln.money_account_id
            if not incoming:
                _withdraw(s, ln.money_account_id, ln.amount)
            entries.append(
                Entry(
                    akind,
                    debit=ln.amount if incoming else ZERO,
                    credit=ZERO if incoming else ln.amount,
                    detail_account_id=ln.money_account_id,
                )
            )
        else:
            assert ln.cheque is not None
            drawn_on: uuid.UUID | None = None
            if not incoming:
                if ln.money_account_id is None:
                    raise DomainError(
                        "حساب بانکی چک پرداختی را انتخاب کنید", code="cheque_account_required"
                    )
                _account(s, actor, ln.money_account_id, doc.branch_id, "bank")
                drawn_on = ln.money_account_id
            cheque = Cheque(
                direction="received" if incoming else "issued",
                status="in_hand" if incoming else "issued",
                party_id=party.id,
                branch_id=doc.branch_id,
                number=ln.cheque.number,
                sayad_id=ln.cheque.sayad_id,
                bank_name=ln.cheque.bank_name,
                drawer=ln.cheque.drawer,
                amount=ln.amount,
                due_date=ln.cheque.due_date,
                money_account_id=drawn_on,
                document_id=doc.id,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
            s.add(cheque)
            s.flush()
            row.cheque_id, row.money_account_id = cheque.id, drawn_on
            entries.append(
                Entry("cheques_receivable", debit=ln.amount, detail_account_id=party.id)
                if incoming
                else Entry("cheques_payable", credit=ln.amount, detail_account_id=party.id)
            )
        doc.lines.append(row)
    entries.append(
        Entry(
            against,
            credit=doc.amount if incoming else ZERO,
            debit=ZERO if incoming else doc.amount,
            detail_account_id=party.id,
        )
    )
    s.flush()
    return document_out(s, _finish(s, actor, doc, entries, pd.name))


def create_receipt(s: Session, actor: Actor, data: ReceiptIn) -> DocumentOut:
    return _receipt_or_payment(s, actor, "receipt", data)


def create_payment(s: Session, actor: Actor, data: ReceiptIn) -> DocumentOut:
    return _receipt_or_payment(s, actor, "payment", data)


# --- transfers and settlements ----------------------------------------------


def create_transfer(s: Session, actor: Actor, data: TransferIn) -> DocumentOut:
    doc = _start(s, actor, "transfer", data.branch_id, data.document_date)
    src_kind, src = _account(s, actor, data.from_account_id, data.branch_id)
    dst_kind, dst = _account(s, actor, data.to_account_id, data.branch_id)
    _withdraw(s, data.from_account_id, data.amount)
    doc.from_account_id, doc.to_account_id = data.from_account_id, data.to_account_id
    doc.amount, doc.reference, doc.description = data.amount, data.reference, data.description
    s.add(doc)
    s.flush()
    entries = [
        Entry(dst_kind, debit=data.amount, detail_account_id=dst.id),
        Entry(src_kind, credit=data.amount, detail_account_id=src.id),
    ]
    return document_out(s, _finish(s, actor, doc, entries, f"{src.name} ← {dst.name}"))


def create_settlement(s: Session, actor: Actor, data: SettlementIn) -> DocumentOut:
    doc = _start(s, actor, "settlement", data.branch_id, data.document_date)
    _, bank = _account(s, actor, data.bank_account_id, data.branch_id, "bank")
    doc.to_account_id = bank.id
    doc.amount, doc.fee = data.amount, data.fee
    doc.reference, doc.description = data.reference, data.description
    s.add(doc)
    s.flush()
    entries = [
        Entry("bank", debit=data.amount - data.fee, detail_account_id=bank.id),
        Entry("fee", debit=data.fee),
        Entry("clearing", credit=data.amount),
    ]
    return document_out(s, _finish(s, actor, doc, entries, bank.name))


# --- reversal ---------------------------------------------------------------


def _get(s: Session, actor: Actor, doc_id: uuid.UUID, lock: bool = False) -> TreasuryDocument:
    doc = s.get(TreasuryDocument, doc_id, with_for_update=lock)
    if doc is None or not actor.can_access_branch(doc.branch_id):
        raise NotFoundError("سند خزانه یافت نشد")
    return doc


def reverse(
    s: Session, actor: Actor, doc_id: uuid.UUID, data: ReverseIn, version: str
) -> DocumentOut:
    doc = _get(s, actor, doc_id, lock=True)
    check_version(doc.row_version, version, "این سند")
    if doc.status != "final":
        raise DomainError("این سند قبلاً برگشت خورده است", code="already_reversed")
    cheques = list(s.scalars(select(Cheque).where(Cheque.document_id == doc.id).with_for_update()))
    for c in cheques:
        if len(c.events) > 1:
            raise DomainError(
                f"وضعیت چک {c.number} تغییر کرده است؛ ابتدا آن را برگردانید",
                code="cheque_moved",
            )
    # Money that came in goes back out: cash must still be there.
    if doc.kind == "receipt":
        for ln in doc.lines:
            if ln.method == "cash" and ln.money_account_id:
                _withdraw(s, ln.money_account_id, ln.amount)
    elif doc.kind == "transfer" and doc.to_account_id:
        _withdraw(s, doc.to_account_id, doc.amount)
    assert doc.voucher_id is not None
    v = s.get(Voucher, doc.voucher_id)
    assert v is not None
    when = data.document_date or doc.document_date
    rev = vouchers.reverse(
        s,
        actor,
        v.id,
        version_to_str(v.row_version),
        when,
        f"برگشت {LABELS[doc.kind]} شماره {doc.number} — {data.reason}",
    )
    for c in cheques:
        c.events.append(
            ChequeEvent(
                seq=len(c.events) + 1,
                event_date=when,
                from_status=c.status,
                to_status="void",
                voucher_id=rev.id,
                note=data.reason,
                created_by=actor.user_id,
            )
        )
        c.status, c.updated_by = "void", actor.user_id
    doc.status = "reversed"
    doc.reversal_voucher_id, doc.reversed_at = rev.id, utcnow()
    doc.reversed_by, doc.reversal_reason = actor.user_id, data.reason
    doc.updated_by = actor.user_id
    s.flush()
    audit.record(
        s,
        f"treasury.{doc.kind}_reversed",
        user_id=actor.user_id,
        branch_id=doc.branch_id,
        entity_type="treasury_document",
        entity_id=doc.id,
        data={"number": doc.number, "reason": data.reason},
    )
    return document_out(s, doc)


# --- queries ----------------------------------------------------------------


def get(s: Session, actor: Actor, doc_id: uuid.UUID) -> DocumentOut:
    return document_out(s, _get(s, actor, doc_id))


def list_documents(s: Session, actor: Actor, q: DocumentQuery) -> Page[DocumentSummary]:
    stmt = select(TreasuryDocument).where(TreasuryDocument.status != "draft")
    if actor.branch_ids is not None:
        stmt = stmt.where(TreasuryDocument.branch_id.in_(actor.branch_ids))
    if q.kind:
        stmt = stmt.where(TreasuryDocument.kind == q.kind)
    if q.status:
        stmt = stmt.where(TreasuryDocument.status == q.status)
    if q.party_id:
        stmt = stmt.where(TreasuryDocument.party_id == q.party_id)
    if q.date_from:
        stmt = stmt.where(TreasuryDocument.document_date >= q.date_from)
    if q.date_to:
        stmt = stmt.where(TreasuryDocument.document_date <= q.date_to)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(TreasuryDocument.document_date.desc(), TreasuryDocument.created_at.desc())
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    names = _names(s, {r.party_id for r in rows} | {r.to_account_id for r in rows})
    return Page(
        items=[
            DocumentSummary(
                id=r.id,
                kind=r.kind,
                status=r.status,
                number=r.number,
                document_date=r.document_date,
                party_name=names.get(r.party_id or r.to_account_id)  # type: ignore[arg-type]
                if (r.party_id or r.to_account_id)
                else None,
                amount=r.amount,
                description=r.description,
            )
            for r in rows
        ],
        total=total,
        page=q.page,
        page_size=q.page_size,
    )
