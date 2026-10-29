"""What the visitor records in the field besides orders (ADR-0026).

* **Collections** are requests: the treasury approves each one, which creates an
  ordinary receipt (voucher from posting rules, cheque in the cheque register) in the
  same unit of work. Until then the customer's balance does not move.
* **New customers** are requests: the back office approves with a detail-account code,
  which creates the party and assigns it to the visitor.
* **Targets** are set per visitor and Jalali month; progress is the invoiced amount.
* **Location** of an assigned customer may be set by its visitor (audited).
Ids of collections and requests are chosen on the phone: a resend returns the same row.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.http import Page
from app.modules.accounting.models import DetailAccount
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.distribution.models import (
    CustomerRequest,
    Visitor,
    VisitorCollection,
    VisitorCustomer,
    VisitorTarget,
)
from app.modules.distribution.schemas import (
    CollectionApproveIn,
    CollectionIn,
    CollectionOut,
    CustomerRequestApproveIn,
    CustomerRequestIn,
    CustomerRequestOut,
    LocationIn,
    RejectIn,
    RequestQuery,
    TargetIn,
    TargetOut,
)
from app.modules.distribution.services import insights, notify, visitors
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.inventory.services.stock import tehran_today
from app.modules.parties.models import Party
from app.modules.parties.schemas import PartyCreateIn
from app.modules.parties.services import core as parties
from app.modules.sales.services import pricing
from app.modules.treasury.models import TreasuryDocument
from app.modules.treasury.schemas import ChequeIn, LineIn, ReceiptIn
from app.modules.treasury.services import documents as treasury

METHOD_FA = {"cash": "نقد", "cheque": "چک", "transfer": "کارت‌به‌کارت"}


def _user_name(s: Session, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    u = s.get(AppUser, user_id)
    return (u.full_name or u.username) if u else None


def _visitor_name(s: Session, v: Visitor | None) -> str:
    return (_user_name(s, v.user_id) or "") if v else ""


def _money(s: Session, rials: Decimal) -> str:
    """An amount for a notification, in the organisation's display currency."""
    if pricing.organization(s).display_currency == "IRT":
        toman = (rials / 10).quantize(Decimal(1)) if rials % 10 == 0 else rials / 10
        return f"{toman:,} تومان"
    return f"{pricing.rial(rials):,} ریال"


def _branch_scope(actor: Actor, stmt, column):  # type: ignore[no-untyped-def]
    if actor.branch_ids is not None:
        stmt = stmt.where(column.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    return stmt


# --- customer location -----------------------------------------------------------------


def set_location(s: Session, actor: Actor, customer_id: uuid.UUID, data: LocationIn) -> None:
    v = visitors.of_actor(s, actor)
    if not visitors.is_assigned(s, v.id, customer_id):
        raise NotFoundError("مشتری یافت نشد")
    party = parties.ensure_party(s, customer_id)
    before = (party.latitude, party.longitude)
    party.latitude, party.longitude = data.latitude, data.longitude
    party.updated_by = actor.user_id
    s.flush()
    audit.record(
        s,
        "distribution.customer_located",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="party",
        entity_id=party.id,
        data={
            "before": [str(x) if x is not None else None for x in before],
            "after": [str(data.latitude), str(data.longitude)],
        },
    )


# --- collections -----------------------------------------------------------------------


def collection_out(s: Session, c: VisitorCollection) -> CollectionOut:
    v = s.get(Visitor, c.visitor_id)
    cust = s.get(DetailAccount, c.customer_id)
    doc = s.get(TreasuryDocument, c.treasury_document_id) if c.treasury_document_id else None
    return CollectionOut(
        id=c.id,
        visitor_id=c.visitor_id,
        visitor_name=_visitor_name(s, v),
        customer_id=c.customer_id,
        customer_name=cust.name if cust else "",
        method=c.method,  # type: ignore[arg-type]
        amount=c.amount,
        collected_at=c.collected_at,
        received_at=c.received_at,
        reference=c.reference,
        cheque_number=c.cheque_number,
        cheque_sayad_id=c.cheque_sayad_id,
        cheque_bank=c.cheque_bank,
        cheque_drawer=c.cheque_drawer,
        cheque_due_date=c.cheque_due_date,
        note=c.note,
        latitude=c.latitude,
        longitude=c.longitude,
        status=c.status,  # type: ignore[arg-type]
        decided_by_name=_user_name(s, c.decided_by),
        decided_at=c.decided_at,
        decision_note=c.decision_note,
        treasury_document_id=c.treasury_document_id,
        treasury_document_number=doc.number if doc else None,
        row_version=version_to_str(c.row_version),
    )


def submit_collection(s: Session, actor: Actor, data: CollectionIn) -> tuple[CollectionOut, bool]:
    v = visitors.of_actor(s, actor)
    found = s.get(VisitorCollection, data.id)
    if found is not None:
        if found.visitor_id != v.id:
            raise ConflictError("این شناسه قبلاً استفاده شده است", code="collection_exists")
        return collection_out(s, found), False
    if not visitors.is_assigned(s, v.id, data.customer_id):
        raise NotFoundError("مشتری یافت نشد")
    now = utcnow()
    c = VisitorCollection(
        id=data.id,
        visitor_id=v.id,
        customer_id=data.customer_id,
        method=data.method,
        amount=data.amount,
        collected_at=min(data.collected_at, now),
        received_at=now,
        reference=data.reference,
        cheque_number=data.cheque_number if data.method == "cheque" else None,
        cheque_sayad_id=data.cheque_sayad_id if data.method == "cheque" else None,
        cheque_bank=data.cheque_bank if data.method == "cheque" else None,
        cheque_drawer=data.cheque_drawer if data.method == "cheque" else None,
        cheque_due_date=data.cheque_due_date if data.method == "cheque" else None,
        note=data.note,
        latitude=data.latitude,
        longitude=data.longitude,
        status="pending",
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(c)
    s.flush()
    audit.record(
        s,
        "distribution.collection_submitted",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="visitor_collection",
        entity_id=c.id,
        data={"amount": str(c.amount), "method": c.method},
    )
    s.refresh(c)
    return collection_out(s, c), True


def my_collections(s: Session, actor: Actor) -> list[CollectionOut]:
    v = visitors.of_actor(s, actor)
    rows = list(
        s.scalars(
            select(VisitorCollection)
            .where(VisitorCollection.visitor_id == v.id)
            .order_by(VisitorCollection.collected_at.desc())
            .limit(100)
        )
    )
    return [collection_out(s, c) for c in rows]


def list_collections(s: Session, actor: Actor, q: RequestQuery) -> Page[CollectionOut]:
    stmt = select(VisitorCollection).join(Visitor, Visitor.id == VisitorCollection.visitor_id)
    stmt = _branch_scope(actor, stmt, Visitor.branch_id)
    if q.status:
        stmt = stmt.where(VisitorCollection.status == q.status)
    if q.visitor_id:
        stmt = stmt.where(VisitorCollection.visitor_id == q.visitor_id)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(VisitorCollection.collected_at.desc())
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    return Page(
        items=[collection_out(s, c) for c in rows], total=total, page=q.page, page_size=q.page_size
    )


def _collection(s: Session, actor: Actor, cid: uuid.UUID) -> tuple[VisitorCollection, Visitor]:
    c = s.get(VisitorCollection, cid, with_for_update=True)
    v = s.get(Visitor, c.visitor_id) if c else None
    if c is None or v is None or not actor.can_access_branch(v.branch_id):
        raise NotFoundError("وصول یافت نشد")
    return c, v


def approve_collection(
    s: Session, actor: Actor, cid: uuid.UUID, data: CollectionApproveIn, version: str
) -> CollectionOut:
    c, v = _collection(s, actor, cid)
    check_version(c.row_version, version, "این وصول")
    if c.status != "pending":
        raise ConflictError("این وصول قبلاً بررسی شده است", code="not_pending")
    if c.method == "cheque":
        assert c.cheque_number is not None and c.cheque_due_date is not None
        line = LineIn(
            method="cheque",
            amount=c.amount,
            cheque=ChequeIn(
                number=c.cheque_number,
                sayad_id=c.cheque_sayad_id,
                bank_name=c.cheque_bank,
                drawer=c.cheque_drawer,
                due_date=c.cheque_due_date,
            ),
        )
    else:
        if data.money_account_id is None:
            raise DomainError(
                "صندوق یا حساب بانکی مقصد را انتخاب کنید", code="money_account_required"
            )
        line = LineIn(
            method="cash" if c.method == "cash" else "bank",
            money_account_id=data.money_account_id,
            amount=c.amount,
            reference=c.reference,
        )
    parties.ensure_party(s, c.customer_id)
    doc = treasury.create_receipt(
        s,
        actor,
        ReceiptIn(
            branch_id=v.branch_id,
            document_date=data.document_date or tehran_today(),
            party_id=c.customer_id,
            description=f"وصول ویزیتور {_visitor_name(s, v)} ({METHOD_FA[c.method]})"
            + (f" — {c.note}" if c.note else ""),
            lines=[line],
        ),
    )
    c.status, c.decided_by, c.decided_at = "approved", actor.user_id, utcnow()
    c.treasury_document_id, c.updated_by = doc.id, actor.user_id
    s.flush()
    audit.record(
        s,
        "distribution.collection_approved",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="visitor_collection",
        entity_id=c.id,
        data={"amount": str(c.amount), "document": doc.number},
    )
    notify.notify(
        s,
        v.id,
        "collection_approved",
        f"وصول {_money(s, c.amount)} ثبت شد",
        f"سند دریافت {doc.number}",
        "collection",
        c.id,
    )
    s.refresh(c)
    return collection_out(s, c)


def reject_collection(
    s: Session, actor: Actor, cid: uuid.UUID, data: RejectIn, version: str
) -> CollectionOut:
    c, v = _collection(s, actor, cid)
    check_version(c.row_version, version, "این وصول")
    if c.status != "pending":
        raise ConflictError("این وصول قبلاً بررسی شده است", code="not_pending")
    c.status, c.decided_by, c.decided_at = "rejected", actor.user_id, utcnow()
    c.decision_note, c.updated_by = data.note, actor.user_id
    s.flush()
    audit.record(
        s,
        "distribution.collection_rejected",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="visitor_collection",
        entity_id=c.id,
        data={"amount": str(c.amount), "note": data.note},
    )
    notify.notify(
        s,
        v.id,
        "collection_rejected",
        f"وصول {_money(s, c.amount)} رد شد",
        f"علت: {data.note}",
        "collection",
        c.id,
    )
    s.refresh(c)
    return collection_out(s, c)


# --- new customers ---------------------------------------------------------------------


def request_out(s: Session, r: CustomerRequest) -> CustomerRequestOut:
    v = s.get(Visitor, r.visitor_id)
    d = s.get(DetailAccount, r.party_id) if r.party_id else None
    return CustomerRequestOut(
        id=r.id,
        visitor_id=r.visitor_id,
        visitor_name=_visitor_name(s, v),
        name=r.name,
        owner_name=r.owner_name,
        mobile=r.mobile,
        phone=r.phone,
        city=r.city,
        address=r.address,
        national_id=r.national_id,
        economic_code=r.economic_code,
        visit_weekday=r.visit_weekday,
        note=r.note,
        latitude=r.latitude,
        longitude=r.longitude,
        status=r.status,  # type: ignore[arg-type]
        created_at=r.created_at,
        decided_by_name=_user_name(s, r.decided_by),
        decided_at=r.decided_at,
        decision_note=r.decision_note,
        party_id=r.party_id,
        party_code=d.code if d else None,
        row_version=version_to_str(r.row_version),
    )


def submit_request(
    s: Session, actor: Actor, data: CustomerRequestIn
) -> tuple[CustomerRequestOut, bool]:
    v = visitors.of_actor(s, actor)
    found = s.get(CustomerRequest, data.id)
    if found is not None:
        if found.visitor_id != v.id:
            raise ConflictError("این شناسه قبلاً استفاده شده است", code="request_exists")
        return request_out(s, found), False
    r = CustomerRequest(
        id=data.id,
        visitor_id=v.id,
        **data.model_dump(exclude={"id"}),
        status="pending",
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(r)
    s.flush()
    audit.record(
        s,
        "distribution.customer_requested",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="customer_request",
        entity_id=r.id,
        data={"name": r.name},
    )
    s.refresh(r)
    return request_out(s, r), True


def my_requests(s: Session, actor: Actor) -> list[CustomerRequestOut]:
    v = visitors.of_actor(s, actor)
    rows = list(
        s.scalars(
            select(CustomerRequest)
            .where(CustomerRequest.visitor_id == v.id)
            .order_by(CustomerRequest.created_at.desc())
            .limit(100)
        )
    )
    return [request_out(s, r) for r in rows]


def list_requests(s: Session, actor: Actor, q: RequestQuery) -> Page[CustomerRequestOut]:
    stmt = select(CustomerRequest).join(Visitor, Visitor.id == CustomerRequest.visitor_id)
    stmt = _branch_scope(actor, stmt, Visitor.branch_id)
    if q.status:
        stmt = stmt.where(CustomerRequest.status == q.status)
    if q.visitor_id:
        stmt = stmt.where(CustomerRequest.visitor_id == q.visitor_id)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(CustomerRequest.created_at.desc())
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    return Page(
        items=[request_out(s, r) for r in rows], total=total, page=q.page, page_size=q.page_size
    )


def _request(s: Session, actor: Actor, rid: uuid.UUID) -> tuple[CustomerRequest, Visitor]:
    r = s.get(CustomerRequest, rid, with_for_update=True)
    v = s.get(Visitor, r.visitor_id) if r else None
    if r is None or v is None or not actor.can_access_branch(v.branch_id):
        raise NotFoundError("درخواست یافت نشد")
    return r, v


def approve_request(
    s: Session, actor: Actor, rid: uuid.UUID, data: CustomerRequestApproveIn, version: str
) -> CustomerRequestOut:
    r, v = _request(s, actor, rid)
    check_version(r.row_version, version, "این درخواست")
    if r.status != "pending":
        raise ConflictError("این درخواست قبلاً بررسی شده است", code="not_pending")
    out = parties.create(
        s,
        actor,
        PartyCreateIn(
            code=data.code,
            name=r.name,
            is_customer=True,
            group_id=data.group_id,
            national_id=r.national_id,
            economic_code=r.economic_code,
            phone=r.phone,
            mobile=r.mobile,
            city=r.city,
            address=r.address,
            credit_limit=data.credit_limit,
        ),
    )
    party = s.get(Party, out.id)
    assert party is not None
    party.latitude, party.longitude = r.latitude, r.longitude
    s.add(
        VisitorCustomer(
            visitor_id=v.id,
            customer_id=out.id,
            visit_weekday=r.visit_weekday,
            created_by=actor.user_id,
            updated_by=actor.user_id,
        )
    )
    r.status, r.decided_by, r.decided_at = "approved", actor.user_id, utcnow()
    r.decision_note, r.party_id, r.updated_by = data.note, out.id, actor.user_id
    s.flush()
    audit.record(
        s,
        "distribution.customer_request_approved",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="customer_request",
        entity_id=r.id,
        data={"party": data.code},
    )
    notify.notify(
        s,
        v.id,
        "customer_approved",
        f"مشتری «{r.name}» تأیید شد",
        "به فهرست مشتریان شما اضافه شد",
        "customer",
        out.id,
    )
    s.refresh(r)
    return request_out(s, r)


def reject_request(
    s: Session, actor: Actor, rid: uuid.UUID, data: RejectIn, version: str
) -> CustomerRequestOut:
    r, v = _request(s, actor, rid)
    check_version(r.row_version, version, "این درخواست")
    if r.status != "pending":
        raise ConflictError("این درخواست قبلاً بررسی شده است", code="not_pending")
    r.status, r.decided_by, r.decided_at = "rejected", actor.user_id, utcnow()
    r.decision_note, r.updated_by = data.note, actor.user_id
    s.flush()
    audit.record(
        s,
        "distribution.customer_request_rejected",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="customer_request",
        entity_id=r.id,
        data={"note": data.note},
    )
    notify.notify(
        s,
        v.id,
        "customer_rejected",
        f"درخواست مشتری «{r.name}» رد شد",
        f"علت: {data.note}",
        "customer_request",
        r.id,
    )
    s.refresh(r)
    return request_out(s, r)


# --- targets ---------------------------------------------------------------------------


def targets(s: Session, actor: Actor, jalali_year: int, jalali_month: int) -> list[TargetOut]:
    if not 1 <= jalali_month <= 12:
        raise DomainError("ماه نامعتبر است", code="bad_month")
    start, end = insights._month_range(jalali_year, jalali_month)
    vs = list(
        s.scalars(_branch_scope(actor, select(Visitor), Visitor.branch_id).order_by(Visitor.code))
    )
    rows = {
        t.visitor_id: t
        for t in s.scalars(
            select(VisitorTarget).where(
                VisitorTarget.jalali_year == jalali_year, VisitorTarget.jalali_month == jalali_month
            )
        )
    }
    out = []
    for v in vs:
        t = rows.get(v.id)
        out.append(
            TargetOut(
                visitor_id=v.id,
                visitor_name=_visitor_name(s, v),
                jalali_year=jalali_year,
                jalali_month=jalali_month,
                amount=t.amount if t else None,
                invoiced=insights._invoiced(s, v.id, start, end)[0],
                row_version=version_to_str(t.row_version) if t else None,
            )
        )
    return out


def set_target(
    s: Session,
    actor: Actor,
    visitor_id: uuid.UUID,
    jalali_year: int,
    jalali_month: int,
    data: TargetIn,
    version: str | None,
) -> TargetOut:
    """Create the month's target, or change it (then ``version`` must be its row version)."""
    if not 1 <= jalali_month <= 12 or not 1390 <= jalali_year <= 1500:
        raise DomainError("ماه نامعتبر است", code="bad_month")
    v = s.get(Visitor, visitor_id)
    if v is None or not actor.can_access_branch(v.branch_id):
        raise NotFoundError("ویزیتور یافت نشد")
    t = s.scalar(
        select(VisitorTarget)
        .where(
            VisitorTarget.visitor_id == v.id,
            VisitorTarget.jalali_year == jalali_year,
            VisitorTarget.jalali_month == jalali_month,
        )
        .with_for_update()
    )
    if t is None:
        t = VisitorTarget(
            visitor_id=v.id,
            jalali_year=jalali_year,
            jalali_month=jalali_month,
            amount=data.amount,
            created_by=actor.user_id,
            updated_by=actor.user_id,
        )
        s.add(t)
    else:
        if not version:
            raise ConflictError(
                "هدف این ماه قبلاً ثبت شده است؛ صفحه را تازه کنید", code="version_conflict"
            )
        check_version(t.row_version, version, "این هدف")
        t.amount, t.updated_by = data.amount, actor.user_id
    s.flush()
    audit.record(
        s,
        "distribution.target_set",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="visitor",
        entity_id=v.id,
        data={"year": jalali_year, "month": jalali_month, "amount": str(data.amount)},
    )
    from app.modules.accounting.services.fiscal import MONTHS

    notify.notify(
        s,
        v.id,
        "target_set",
        f"هدف {MONTHS[jalali_month - 1]} {jalali_year} تعیین شد",
        _money(s, data.amount),
        "target",
        t.id,
    )
    s.refresh(t)
    start, end = insights._month_range(jalali_year, jalali_month)
    return TargetOut(
        visitor_id=v.id,
        visitor_name=_visitor_name(s, v),
        jalali_year=jalali_year,
        jalali_month=jalali_month,
        amount=t.amount,
        invoiced=insights._invoiced(s, v.id, start, end)[0],
        row_version=version_to_str(t.row_version),
    )
