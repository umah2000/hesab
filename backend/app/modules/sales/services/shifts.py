"""Cash shifts: open with a float, close with a count; the difference is posted."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from app.modules.accounting.services.chart import check_version
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.audit import service as audit
from app.modules.devices.models import Device
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.inventory.services.stock import tehran_today
from app.modules.organization.models import CashRegister
from app.modules.sales.models import CashShift, SalesInvoice, SalesPayment, TerminalTransaction
from app.modules.sales.schemas import (
    MethodTotal,
    ShiftCloseIn,
    ShiftOpenIn,
    ShiftOut,
    ShiftReportOut,
)
from app.modules.sales.services.pricing import register_and_warehouse

ZERO = Decimal(0)
UNRESOLVED = ("Created", "Pending", "Unknown", "ReconciliationRequired")


def shift_out(s: Session, sh: CashShift) -> ShiftOut:
    reg = s.get(CashRegister, sh.cash_register_id)
    user = s.get(AppUser, sh.user_id)
    return ShiftOut(
        id=sh.id,
        branch_id=sh.branch_id,
        cash_register_id=sh.cash_register_id,
        register_name=reg.name if reg else "",
        user_id=sh.user_id,
        user_name=(user.full_name or user.username) if user else "",
        status=sh.status,  # type: ignore[arg-type]
        opened_at=sh.opened_at,
        opening_cash=sh.opening_cash,
        closed_at=sh.closed_at,
        expected_cash=sh.expected_cash,
        counted_cash=sh.counted_cash,
        difference=sh.difference,
        close_note=sh.close_note,
        voucher_id=sh.voucher_id,
        row_version=version_to_str(sh.row_version),
    )


def open_shift_of(s: Session, user_id: uuid.UUID) -> CashShift | None:
    return s.scalar(
        select(CashShift).where(CashShift.user_id == user_id, CashShift.status == "open")
    )


def open_shift_on(s: Session, register_id: uuid.UUID) -> CashShift | None:
    return s.scalar(
        select(CashShift).where(
            CashShift.cash_register_id == register_id, CashShift.status == "open"
        )
    )


def require_open_shift(s: Session, actor: Actor, register_id: uuid.UUID) -> CashShift:
    sh = open_shift_of(s, actor.user_id)
    if sh is None or sh.cash_register_id != register_id:
        raise DomainError(
            "شیفت باز روی این صندوق ندارید؛ ابتدا شیفت را باز کنید", code="no_open_shift"
        )
    return sh


def open_shift(s: Session, actor: Actor, data: ShiftOpenIn) -> ShiftOut:
    reg, _ = register_and_warehouse(s, data.cash_register_id, actor.branch_ids)
    if open_shift_of(s, actor.user_id) is not None:
        raise ConflictError("شما یک شیفت باز دارید؛ ابتدا آن را ببندید", code="shift_already_open")
    other = open_shift_on(s, reg.id)
    if other is not None:
        user = s.get(AppUser, other.user_id)
        raise ConflictError(
            f"شیفت «{user.full_name if user else ''}» روی این صندوق باز است", code="register_busy"
        )
    sh = CashShift(
        branch_id=reg.branch_id,
        cash_register_id=reg.id,
        user_id=actor.user_id,
        status="open",
        opened_at=utcnow(),
        opening_cash=data.opening_cash,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(sh)
    try:
        s.flush()
    except IntegrityError as e:  # a concurrent open on the same register or by the same user
        raise ConflictError("شیفت دیگری هم‌زمان باز شد", code="register_busy") from e
    audit.record(
        s,
        "sales.shift_opened",
        user_id=actor.user_id,
        branch_id=reg.branch_id,
        entity_type="cash_shift",
        entity_id=sh.id,
        data={"register": reg.code, "opening_cash": str(data.opening_cash)},
    )
    s.refresh(sh)
    return shift_out(s, sh)


def _method_totals(s: Session, shift_id: uuid.UUID) -> dict[tuple[str, str], Decimal]:
    rows = s.execute(
        select(SalesInvoice.kind, SalesPayment.method, func.sum(SalesPayment.amount))
        .join(SalesInvoice, SalesInvoice.id == SalesPayment.invoice_id)
        .where(SalesInvoice.shift_id == shift_id, SalesInvoice.status == "final")
        .group_by(SalesInvoice.kind, SalesPayment.method)
    ).all()
    return {(k, m): Decimal(v or 0) for k, m, v in rows}


def expected_cash(s: Session, sh: CashShift) -> Decimal:
    t = _method_totals(s, sh.id)
    return sh.opening_cash + t.get(("sale", "cash"), ZERO) - t.get(("return", "cash"), ZERO)


def report(s: Session, actor: Actor, shift_id: uuid.UUID) -> ShiftReportOut:
    sh = _get(s, actor, shift_id)
    t = _method_totals(s, sh.id)
    agg = s.execute(
        select(
            SalesInvoice.kind,
            func.count(),
            func.sum(SalesInvoice.grand_total),
            func.sum(SalesInvoice.discount_total),
            func.sum(SalesInvoice.tax_total),
        )
        .where(SalesInvoice.shift_id == sh.id, SalesInvoice.status == "final")
        .group_by(SalesInvoice.kind)
    ).all()
    by_kind = {
        k: (int(c), Decimal(g or 0), Decimal(d or 0), Decimal(x or 0)) for k, c, g, d, x in agg
    }
    sale = by_kind.get("sale", (0, ZERO, ZERO, ZERO))
    ret = by_kind.get("return", (0, ZERO, ZERO, ZERO))
    return ShiftReportOut(
        shift=shift_out(s, sh),
        sale_count=sale[0],
        return_count=ret[0],
        sales_total=sale[1],
        returns_total=ret[1],
        discount_total=sale[2] - ret[2],
        tax_total=sale[3] - ret[3],
        by_method=[
            MethodTotal(
                method=m,
                sales=t.get(("sale", m), ZERO),
                refunds=t.get(("return", m), ZERO),
            )
            for m in ("cash", "card", "credit")
        ],
        expected_cash=sh.expected_cash
        if sh.status == "closed" and sh.expected_cash is not None
        else expected_cash(s, sh),
    )


def _get(s: Session, actor: Actor, shift_id: uuid.UUID) -> CashShift:
    sh = s.get(CashShift, shift_id)
    if sh is None or not actor.can_access_branch(sh.branch_id):
        raise NotFoundError("شیفت یافت نشد")
    if sh.user_id != actor.user_id and not actor.has("sales.report.view"):
        raise NotFoundError("شیفت یافت نشد")
    return sh


def close_shift(
    s: Session, actor: Actor, shift_id: uuid.UUID, data: ShiftCloseIn, version: str
) -> ShiftOut:
    sh = s.scalar(select(CashShift).where(CashShift.id == shift_id).with_for_update())
    if sh is None or not actor.can_access_branch(sh.branch_id):
        raise NotFoundError("شیفت یافت نشد")
    if sh.user_id != actor.user_id and not actor.has("sales.report.view"):
        raise PermissionDeniedError("بستن شیفت کاربر دیگر فقط با مجوز سرپرست ممکن است")
    if sh.status != "open":
        raise ConflictError("این شیفت قبلاً بسته شده است", code="shift_closed")
    check_version(sh.row_version, version, "این شیفت")
    pending = s.scalar(
        select(func.count())
        .select_from(TerminalTransaction)
        .where(
            TerminalTransaction.cash_register_id == sh.cash_register_id,
            TerminalTransaction.status.in_(UNRESOLVED),
            TerminalTransaction.created_at >= sh.opened_at,
        )
    )
    if pending:
        raise DomainError(
            "تراکنش کارت‌خوان با وضعیت نامشخص روی این صندوق هست؛ ابتدا آن را روشن کنید",
            code="unresolved_card_transaction",
        )
    # Offline sales still on the register belong in this count (ADR-0017).
    waiting = s.scalar(
        select(func.coalesce(func.sum(Device.offline_queue), 0)).where(
            Device.cash_register_id == sh.cash_register_id, Device.status == "active"
        )
    )
    if waiting:
        raise DomainError(
            f"{waiting} فروش آفلاین هنوز از صندوق به سرور نرسیده است؛ "
            "پس از همگام‌سازی شیفت را ببندید",
            code="offline_sales_pending",
        )
    expected = expected_cash(s, sh)
    diff = data.counted_cash - expected
    sh.expected_cash, sh.counted_cash, sh.difference = expected, data.counted_cash, diff
    sh.close_note = data.note
    sh.status, sh.closed_at, sh.closed_by = "closed", utcnow(), actor.user_id
    sh.updated_by, sh.updated_at = actor.user_id, utcnow()
    if diff:
        reg = s.get(CashRegister, sh.cash_register_id)
        entries = (
            [Entry("shortage", debit=-diff), Entry("cash", credit=-diff)]
            if diff < 0
            else [Entry("cash", debit=diff), Entry("overage", credit=diff)]
        )
        v = post_event(
            s,
            event_type="sales.shift.closed",
            document_date=tehran_today(),
            branch_id=sh.branch_id,
            entries=entries,
            actor_id=actor.user_id,
            source_id=sh.id,
            description=f"{'کسری' if diff < 0 else 'اضافه'} صندوق {reg.name if reg else ''}",
        )
        sh.voucher_id = v.id
    s.flush()
    audit.record(
        s,
        "sales.shift_closed",
        user_id=actor.user_id,
        branch_id=sh.branch_id,
        entity_type="cash_shift",
        entity_id=sh.id,
        data={
            "expected": str(expected),
            "counted": str(data.counted_cash),
            "difference": str(diff),
        },
    )
    s.refresh(sh)
    return shift_out(s, sh)


def list_shifts(
    s: Session, actor: Actor, register_id: uuid.UUID | None, page: int, page_size: int
) -> tuple[list[ShiftOut], int]:
    stmt = select(CashShift)
    if register_id:
        stmt = stmt.where(CashShift.cash_register_id == register_id)
    if actor.branch_ids is not None:
        stmt = stmt.where(CashShift.branch_id.in_(actor.branch_ids))
    if not actor.has("sales.report.view"):
        stmt = stmt.where(CashShift.user_id == actor.user_id)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(CashShift.opened_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return [shift_out(s, sh) for sh in rows], int(total)
