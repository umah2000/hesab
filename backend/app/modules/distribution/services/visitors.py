"""Visitors and the customers assigned to them (ADR-0018)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from app.modules.accounting.models import DetailAccount
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.distribution.models import Visitor, VisitorCustomer
from app.modules.distribution.schemas import (
    AssignedCustomerOut,
    AssignmentsIn,
    VisitorIn,
    VisitorOut,
    VisitorUpdateIn,
)
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser, MobileSession
from app.modules.organization.models import Branch
from app.modules.parties.models import Party
from app.modules.sales.services.invoices import receivable_balance

ZERO = Decimal(0)


def visitor_out(s: Session, v: Visitor) -> VisitorOut:
    user = s.get(AppUser, v.user_id)
    branch = s.get(Branch, v.branch_id)
    count = s.scalar(
        select(func.count()).select_from(VisitorCustomer).where(VisitorCustomer.visitor_id == v.id)
    )
    seen = s.scalar(
        select(func.max(MobileSession.last_seen_at)).where(MobileSession.user_id == v.user_id)
    )
    return VisitorOut(
        id=v.id,
        user_id=v.user_id,
        username=user.username if user else "",
        name=(user.full_name or user.username) if user else "",
        branch_id=v.branch_id,
        branch_name=branch.name if branch else "",
        code=v.code,
        is_active=v.is_active,
        note=v.note,
        customer_count=count or 0,
        last_seen_at=seen,
        row_version=version_to_str(v.row_version),
    )


def _get(s: Session, actor: Actor, visitor_id: uuid.UUID) -> Visitor:
    v = s.get(Visitor, visitor_id)
    if v is None or not actor.can_access_branch(v.branch_id):
        raise NotFoundError("ویزیتور یافت نشد")
    return v


def list_visitors(s: Session, actor: Actor) -> list[VisitorOut]:
    q = select(Visitor).order_by(Visitor.code)
    if actor.branch_ids is not None:
        q = q.where(Visitor.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    return [visitor_out(s, v) for v in list(s.scalars(q))]


def get(s: Session, actor: Actor, visitor_id: uuid.UUID) -> VisitorOut:
    return visitor_out(s, _get(s, actor, visitor_id))


def _check_branch(s: Session, actor: Actor, branch_id: uuid.UUID) -> None:
    b = s.get(Branch, branch_id)
    if b is None or not actor.can_access_branch(branch_id):
        raise NotFoundError("شعبه یافت نشد")


def create(s: Session, actor: Actor, data: VisitorIn) -> VisitorOut:
    _check_branch(s, actor, data.branch_id)
    user = s.get(AppUser, data.user_id)
    if user is None or not user.is_active:
        raise NotFoundError("کاربر یافت نشد")
    if "distribution.visitor" not in user.permission_codes:
        raise DomainError(
            "این کاربر نقش «ویزیتور» (مجوز اپلیکیشن ویزیتور) ندارد", code="not_a_visitor"
        )
    if s.scalar(select(Visitor.id).where(Visitor.user_id == user.id)):
        raise ConflictError("برای این کاربر ویزیتور تعریف شده است", code="visitor_exists")
    if s.scalar(select(Visitor.id).where(Visitor.code == data.code.upper())):
        raise ConflictError("این کد ویزیتور تکراری است", code="duplicate_code")
    v = Visitor(
        user_id=user.id,
        branch_id=data.branch_id,
        code=data.code.upper(),
        note=data.note,
        is_active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(v)
    s.flush()
    audit.record(
        s,
        "distribution.visitor_created",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="visitor",
        entity_id=v.id,
        data={"code": v.code, "user": user.username},
    )
    s.refresh(v)
    return visitor_out(s, v)


def update(
    s: Session, actor: Actor, visitor_id: uuid.UUID, data: VisitorUpdateIn, version: str
) -> VisitorOut:
    v = _get(s, actor, visitor_id)
    check_version(v.row_version, version, "این ویزیتور")
    _check_branch(s, actor, data.branch_id)
    v.branch_id, v.is_active, v.note = data.branch_id, data.is_active, data.note
    v.updated_by = actor.user_id
    s.flush()
    audit.record(
        s,
        "distribution.visitor_updated",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="visitor",
        entity_id=v.id,
        data={"is_active": v.is_active},
    )
    s.refresh(v)
    return visitor_out(s, v)


def assigned(s: Session, visitor_id: uuid.UUID) -> list[AssignedCustomerOut]:
    rows = s.execute(
        select(VisitorCustomer, DetailAccount, Party)
        .join(DetailAccount, DetailAccount.id == VisitorCustomer.customer_id)
        .outerjoin(Party, Party.id == DetailAccount.id)
        .where(VisitorCustomer.visitor_id == visitor_id)
        .order_by(DetailAccount.name)
    ).all()
    out = []
    for vc, acc, party in rows:
        balance = receivable_balance(s, acc.id)
        out.append(
            AssignedCustomerOut(
                customer_id=acc.id,
                code=acc.code,
                name=acc.name,
                phone=(party.mobile or party.phone) if party else None,
                address=party.address if party else None,
                visit_weekday=vc.visit_weekday,
                credit_limit=acc.credit_limit,
                balance=balance,
                available=acc.credit_limit - balance if acc.credit_limit is not None else None,
            )
        )
    return out


def customers(s: Session, actor: Actor, visitor_id: uuid.UUID) -> list[AssignedCustomerOut]:
    return assigned(s, _get(s, actor, visitor_id).id)


def assign(
    s: Session, actor: Actor, visitor_id: uuid.UUID, data: AssignmentsIn
) -> list[AssignedCustomerOut]:
    """Replace the visitor's customers (and visit days) with this list."""
    v = _get(s, actor, visitor_id)
    ids = [a.customer_id for a in data.customers]
    if len(set(ids)) != len(ids):
        raise DomainError("مشتری تکراری در فهرست است", code="duplicate_customer")
    if ids:
        found = {
            a.id
            for a in s.scalars(
                select(DetailAccount).where(
                    DetailAccount.id.in_(ids), DetailAccount.kind == "person"
                )
            )
        }
        if len(found) != len(ids):
            raise NotFoundError("مشتری یافت نشد")
    s.execute(delete(VisitorCustomer).where(VisitorCustomer.visitor_id == v.id))
    for a in data.customers:
        s.add(
            VisitorCustomer(
                visitor_id=v.id,
                customer_id=a.customer_id,
                visit_weekday=a.visit_weekday,
                created_by=actor.user_id,
                updated_by=actor.user_id,
            )
        )
    s.flush()
    audit.record(
        s,
        "distribution.customers_assigned",
        user_id=actor.user_id,
        branch_id=v.branch_id,
        entity_type="visitor",
        entity_id=v.id,
        data={"count": len(ids)},
    )
    return assigned(s, v.id)


def of_actor(s: Session, actor: Actor) -> Visitor:
    """The visitor record of the signed-in app user."""
    v = s.scalar(select(Visitor).where(Visitor.user_id == actor.user_id))
    if v is None or not v.is_active:
        raise PermissionDeniedError(
            "برای شما ویزیتور فعال تعریف نشده است؛ با مدیر فروش تماس بگیرید",
            code="no_visitor",
        )
    return v


def is_assigned(s: Session, visitor_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
    return (
        s.scalar(
            select(VisitorCustomer.id).where(
                VisitorCustomer.visitor_id == visitor_id,
                VisitorCustomer.customer_id == customer_id,
            )
        )
        is not None
    )
