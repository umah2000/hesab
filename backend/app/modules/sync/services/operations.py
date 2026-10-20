"""Offline operations for people: the inbox of conflicts and rejections, and resolving them."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.http import Page
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.devices.models import Device
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.organization.models import CashRegister
from app.modules.sales.models import SalesInvoice
from app.modules.sync.models import SyncOperation
from app.modules.sync.schemas import OfflineOpIn, OperationOut, OperationQuery, ResolveIn
from app.modules.sync.services.apply import apply_sale

OPEN = ("conflict", "rejected")


def _user_name(s: Session, user_id: uuid.UUID | None) -> str | None:
    u = s.get(AppUser, user_id) if user_id else None
    return (u.full_name or u.username) if u else None


def operation_out(s: Session, op: SyncOperation) -> OperationOut:
    d = s.get(Device, op.device_id)
    reg = s.get(CashRegister, d.cash_register_id) if d and d.cash_register_id else None
    inv = s.get(SalesInvoice, op.invoice_id) if op.invoice_id else None
    sale: dict[str, object] = {}
    try:
        raw = json.loads(op.payload)
        if isinstance(raw, dict) and isinstance(raw.get("sale"), dict):
            sale = raw["sale"]
    except ValueError:
        pass
    sold_at = None
    if isinstance(sale.get("sold_at"), str):
        try:
            sold_at = datetime.fromisoformat(str(sale["sold_at"]))
        except ValueError:
            sold_at = None
    total: Decimal | None = None
    try:
        total = Decimal(str(sale["grand_total"])) if "grand_total" in sale else None
    except ArithmeticError:
        total = None
    cashier = None
    try:
        cashier = _user_name(s, uuid.UUID(str(sale["user_id"]))) if "user_id" in sale else None
    except ValueError:
        cashier = None
    return OperationOut(
        id=op.id,
        device_id=op.device_id,
        device_name=d.name if d else "",
        register_name=reg.name if reg else None,
        op_type=op.op_type,
        status=op.status,
        device_number=op.device_number,
        sold_at=sold_at,
        local_time=op.local_time,
        received_at=op.received_at,
        cashier_name=cashier,
        grand_total=total,
        code=op.code,
        message=op.message,
        price_difference=op.price_difference,
        invoice_id=op.invoice_id,
        invoice_number=inv.number if inv else None,
        resolved_by_name=_user_name(s, op.resolved_by),
        resolved_at=op.resolved_at,
        resolution_note=op.resolution_note,
        row_version=version_to_str(op.row_version),
    )


def _visible(actor: Actor) -> Select[SyncOperation]:
    q = select(SyncOperation).join(Device, Device.id == SyncOperation.device_id)
    if actor.branch_ids is not None:
        q = q.where(Device.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
    return q


def list_operations(s: Session, actor: Actor, query: OperationQuery) -> Page[OperationOut]:
    q = _visible(actor)
    if query.status == "open":
        q = q.where(SyncOperation.status.in_(OPEN))
    elif query.status:
        q = q.where(SyncOperation.status == query.status)
    if query.device_id:
        q = q.where(SyncOperation.device_id == query.device_id)
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(
        s.scalars(
            q.order_by(SyncOperation.received_at.desc(), SyncOperation.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    )
    return Page(
        items=[operation_out(s, op) for op in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


def open_count(s: Session, actor: Actor) -> int:
    q = _visible(actor).where(SyncOperation.status.in_(OPEN))
    return s.scalar(select(func.count()).select_from(q.subquery())) or 0


def get(s: Session, actor: Actor, op_id: uuid.UUID, lock: bool = False) -> SyncOperation:
    op = s.get(SyncOperation, op_id, with_for_update=lock)
    d = s.get(Device, op.device_id) if op else None
    if op is None or d is None or not actor.can_access_branch(d.branch_id):
        raise NotFoundError("عملیات یافت نشد")
    return op


def resolve(
    s: Session, actor: Actor, op_id: uuid.UUID, data: ResolveIn, version: str
) -> OperationOut:
    op = get(s, actor, op_id, lock=True)
    check_version(op.row_version, version, "این عملیات")
    if op.status not in OPEN:
        raise ConflictError("این عملیات قبلاً رسیدگی شده است", code="already_resolved")
    if data.action == "apply":
        if op.status != "conflict":
            raise DomainError(
                "فروش ردشده قابل ثبت نیست؛ فقط می‌توان آن را کنار گذاشت", code="not_applicable"
            )
        d = s.get(Device, op.device_id)
        assert d is not None
        sale = OfflineOpIn.model_validate(json.loads(op.payload)).sale
        assert sale is not None  # only sales can be in conflict
        done = apply_sale(s, d, sale, force=True)
        op.invoice_id, op.price_difference = done.invoice.id, done.price_difference
        op.status = "resolved"
    else:
        op.status = "discarded"
    op.resolved_by, op.resolved_at, op.resolution_note = actor.user_id, utcnow(), data.note
    s.flush()
    audit.record(
        s,
        f"sync.operation.{op.status}",
        user_id=actor.user_id,
        entity_type="sync_operation",
        entity_id=op.id,
        data={"code": op.code, "note": data.note, "invoice_id": str(op.invoice_id or "")},
    )
    s.flush()
    s.refresh(op)
    return operation_out(s, op)
