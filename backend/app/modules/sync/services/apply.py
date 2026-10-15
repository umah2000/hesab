"""Applying sales a register made while the server was out of reach (ADR-0017).

The sale already happened: the customer paid what the receipt says and left with the
goods. So the server records it as sold, never reprices it, and never silently changes
it:

* each operation is applied once (its id is the invoice id); a resend gets the stored
  result;
* arithmetic that does not add up, a foreign register or shift → ``rejected``;
* anything a person must judge (the shift or fiscal period is already closed, the
  register's clock looks wrong, the cashier lacked a permission) → ``conflict``, kept
  with its payload until a manager applies or discards it (``sync.resolve``);
* stock is issued on the day of sync (the ledger never goes backwards; negative stock is
  allowed, the goods are gone) while the invoice and its voucher carry the sale date;
* the gap-free number is taken at sync; the register's number is kept beside it;
* any difference from the server's current prices is recorded, never corrected.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import new_session, unit_of_work, utcnow
from app.core.errors import DomainError
from app.modules.accounting.services.fiscal import open_year_for
from app.modules.devices.models import Device
from app.modules.iam.models import AppUser
from app.modules.inventory.models import Item, ItemUnit
from app.modules.inventory.services.stock import tehran_today
from app.modules.sales.models import CashShift, SalesInvoice, SalesInvoiceLine, SalesPayment
from app.modules.sales.services import pricing
from app.modules.sales.services.invoices import METHOD_PERMISSION, _Tender, book_sale
from app.modules.sync.models import SyncOperation
from app.modules.sync.schemas import OfflineOpIn, OfflineSaleIn, PushResult
from app.modules.sync.services.snapshot import number_prefix

ZERO = Decimal(0)
HUNDRED = Decimal(100)
CLOCK_SLACK = timedelta(minutes=5)
TEHRAN = ZoneInfo("Asia/Tehran")


class Rejected(DomainError):
    """The payload itself is wrong; applying it later cannot help."""

    status_code = 422


@dataclass
class Applied:
    invoice: SalesInvoice
    price_difference: Decimal | None
    code: str | None = None
    message: str | None = None


# --- checks ---------------------------------------------------------------------


def _check_totals(sale: OfflineSaleIn) -> None:
    bad = Rejected("مبالغ فاکتور آفلاین با هم نمی‌خوانند", code="bad_totals")
    for ln in sale.lines:
        if ln.vat_exempt and ln.vat_rate:
            raise bad
        if ln.price_source == "list" and ln.gross != pricing.rial(ln.qty * ln.unit_price):
            raise bad
        net = ln.gross - ln.promotion_discount - ln.manual_discount
        if net < 0:
            raise bad
        if sale.prices_include_vat:
            tax, total = pricing.rial(net * ln.vat_rate / (HUNDRED + ln.vat_rate)), net
        else:
            tax = pricing.rial(net * ln.vat_rate / HUNDRED)
            total = net + tax
        if ln.tax != tax or ln.line_total != total:
            raise bad
    if (
        sale.subtotal != sum((ln.gross for ln in sale.lines), ZERO)
        or sale.discount_total
        != sum((ln.promotion_discount + ln.manual_discount for ln in sale.lines), ZERO)
        or sale.tax_total != sum((ln.tax for ln in sale.lines), ZERO)
        or sale.grand_total != sum((ln.line_total for ln in sale.lines), ZERO)
    ):
        raise bad
    if sum((p.amount for p in sale.payments), ZERO) != sale.grand_total:
        raise Rejected("جمع پرداخت‌ها با مبلغ فاکتور برابر نیست", code="payment_mismatch")
    for p in sale.payments:
        if p.method == "card" and not p.card_reference:
            raise Rejected("پرداخت کارتی بدون شماره پیگیری", code="card_reference_required")
    cash = sum((p.amount for p in sale.payments if p.method == "cash"), ZERO)
    if sale.cash_tendered is not None and sale.cash_tendered < cash:
        raise Rejected("وجه دریافتی از مبلغ نقدی کمتر است", code="tendered_too_low")


def _check_permissions(user: AppUser, sale: OfflineSaleIn, limit: Decimal) -> None:
    perms = user.permission_codes
    if not user.is_active or "sales.pos.use" not in perms:
        raise DomainError("صندوق‌دار مجوز فروش ندارد", code="not_permitted")
    for p in sale.payments:
        if METHOD_PERMISSION[p.method] not in perms:
            raise DomainError("صندوق‌دار مجوز این روش پرداخت را ندارد", code="not_permitted")
    manual = sum((ln.manual_discount for ln in sale.lines), ZERO)
    if manual and "sales.invoice.discount_over_limit" not in perms:
        percent = manual * HUNDRED / sale.subtotal if sale.subtotal else HUNDRED
        if "sales.invoice.discount" not in perms or percent > limit:
            raise DomainError(
                "تخفیف دستی این فروش بیش از اختیار صندوق‌دار است", code="not_permitted"
            )


def _price_difference(
    s: Session, sale: OfflineSaleIn, warehouse_id: uuid.UUID, on: Any
) -> Decimal | None:
    """Sold total minus the server's price for the same cart (current prices)."""
    lines = [
        pricing.LineIn(
            item_id=ln.item_id,
            qty=ln.qty,
            unit_id=ln.unit_id,
            barcode=ln.scanned_barcode,
            manual_discount=ln.manual_discount,
        )
        for ln in sale.lines
    ]
    try:
        server = pricing.price_lines(s, lines, warehouse_id=warehouse_id, today=on)
    except DomainError:
        return None
    return sale.grand_total - server.grand_total


# --- apply ----------------------------------------------------------------------


def apply_sale(s: Session, d: Device, sale: OfflineSaleIn, *, force: bool = False) -> Applied:
    """Record one offline sale. ``force`` = a manager accepted the conflict."""
    if d.cash_register_id is None or sale.cash_register_id != d.cash_register_id:
        raise Rejected("فروش متعلق به صندوق این دستگاه نیست", code="wrong_register")
    if not sale.device_number.startswith(number_prefix(d) + "-"):
        raise Rejected("شماره فیش با این دستگاه نمی‌خواند", code="wrong_number")
    _check_totals(sale)

    found = s.get(SalesInvoice, sale.id)
    if found is not None:
        # The online checkout went through but its answer never reached the register.
        if found.status == "final" and found.grand_total == sale.grand_total:
            return Applied(
                found,
                ZERO,
                "already_recorded",
                "این فروش پیش‌تر به‌صورت آنلاین ثبت شده بود",
            )
        raise Rejected("فاکتوری با این شناسه و مبلغ دیگر در سرور هست", code="invoice_exists")
    if s.scalar(select(SalesInvoice.id).where(SalesInvoice.device_number == sale.device_number)):
        raise Rejected("این شماره فیش قبلاً ثبت شده است", code="duplicate_number")

    reg, wh = pricing.register_and_warehouse(s, d.cash_register_id, None)
    shift = s.get(CashShift, sale.shift_id)
    user = s.get(AppUser, sale.user_id)
    if (
        shift is None
        or user is None
        or shift.cash_register_id != reg.id
        or shift.user_id != sale.user_id
    ):
        raise Rejected("شیفت فروش آفلاین با صندوق و صندوق‌دار نمی‌خواند", code="bad_shift")

    now = utcnow()
    opened = shift.opened_at.replace(tzinfo=shift.opened_at.tzinfo or ZoneInfo("UTC"))
    if not force:
        if sale.sold_at > now + CLOCK_SLACK or sale.sold_at < opened - CLOCK_SLACK:
            raise DomainError(
                "ساعت صندوق با زمان شیفت نمی‌خواند؛ تاریخ فروش را بررسی کنید", code="clock"
            )
        if shift.status != "open":
            raise DomainError("شیفت این فروش پیش از رسیدن آن بسته شده است", code="shift_closed")
        _check_permissions(user, sale, pricing.organization(s).cashier_discount_limit)

    today = tehran_today()
    sale_date = min(sale.sold_at.astimezone(TEHRAN).date(), today)
    try:
        fy = open_year_for(s, sale_date)
    except DomainError:
        if not force:
            raise
        sale_date = today  # the manager books it on the day it was resolved
        fy = open_year_for(s, sale_date)
    stock_fy = open_year_for(s, today)

    ids = list({ln.item_id for ln in sale.lines})
    items = {i.id: i for i in s.scalars(select(Item).where(Item.id.in_(ids)))}
    factors = {
        (u.item_id, u.unit_id): u.factor
        for u in s.scalars(select(ItemUnit).where(ItemUnit.item_id.in_(list(items))))
    }
    difference = _price_difference(s, sale, wh.id, sale_date)

    tender = _Tender()
    for p in sale.payments:
        setattr(tender, p.method, getattr(tender, p.method) + p.amount)
    inv = SalesInvoice(
        id=sale.id,
        branch_id=reg.branch_id,
        cash_register_id=reg.id,
        shift_id=shift.id,
        fiscal_year_id=fy.id,
        warehouse_id=wh.id,
        kind="sale",
        status="draft",
        document_date=sale_date,
        subtotal=sale.subtotal,
        discount_total=sale.discount_total,
        tax_total=sale.tax_total,
        grand_total=sale.grand_total,
        cash_tendered=sale.cash_tendered,
        change_due=sale.cash_tendered - tender.cash if sale.cash_tendered is not None else None,
        note=sale.note,
        device_number=sale.device_number,
        sold_at=sale.sold_at,
        created_by=user.id,
        updated_by=user.id,
    )
    s.add(inv)
    lines = []
    for no, ln in enumerate(sale.lines, start=1):
        item = items.get(ln.item_id)
        if item is None:
            raise Rejected("کالای فروش آفلاین در سرور نیست", code="unknown_item")
        factor = (
            Decimal(1) if ln.unit_id == item.base_unit_id else factors.get((item.id, ln.unit_id))
        )
        if factor is None:
            raise Rejected(f"واحد «{item.name}» در سرور تعریف نشده است", code="unknown_unit")
        row = SalesInvoiceLine(
            line_no=no,
            item_id=item.id,
            unit_id=ln.unit_id,
            qty=ln.qty,
            base_qty=(ln.qty * factor).quantize(Decimal("0.001")),
            unit_price=ln.unit_price,
            price_source=ln.price_source,
            gross=ln.gross,
            promotion_id=ln.promotion_id,
            promotion_discount=ln.promotion_discount,
            manual_discount=ln.manual_discount,
            vat_exempt=ln.vat_exempt,
            vat_rate=ln.vat_rate,
            tax=ln.tax,
            revenue=ln.line_total - ln.tax,
            line_total=ln.line_total,
            scanned_barcode=ln.scanned_barcode,
        )
        inv.lines.append(row)
        lines.append((row, pricing.item_ref(item)))
    for i, p in enumerate(sale.payments, start=1):
        inv.payments.append(
            SalesPayment(
                seq=i,
                method=p.method,
                amount=p.amount,
                card_reference=p.card_reference if p.method == "card" else None,
            )
        )
    s.flush()
    book_sale(
        s,
        inv,
        lines,
        tender,
        fiscal_year_id=fy.id,
        register_name=reg.name,
        allow_negative=True,
        actor_id=user.id,
        stock_date=today,
        stock_fiscal_year_id=stock_fy.id,
    )
    return Applied(inv, difference)


# --- push -----------------------------------------------------------------------


def result_of(op: SyncOperation, number: int | None = None) -> PushResult:
    return PushResult(
        id=op.id,
        status=op.status,  # type: ignore[arg-type]
        code=op.code,
        message=op.message,
        invoice_id=op.invoice_id,
        number=number,
    )


def _stored(s: Session, op: SyncOperation) -> PushResult:
    inv = s.get(SalesInvoice, op.invoice_id) if op.invoice_id else None
    return result_of(op, inv.number if inv else None)


def _parse_time(raw: Any) -> datetime:
    try:
        t = datetime.fromisoformat(str(raw))
        return t if t.tzinfo else utcnow()
    except ValueError:
        return utcnow()


def _record(
    device_id: uuid.UUID,
    op_id: uuid.UUID,
    raw: dict[str, Any],
    status: str,
    code: str | None,
    message: str,
) -> PushResult:
    sale = raw.get("sale") if isinstance(raw.get("sale"), dict) else {}
    number = sale.get("device_number") if isinstance(sale, dict) else None
    try:
        with unit_of_work() as s:
            op = SyncOperation(
                id=op_id,
                device_id=device_id,
                op_type="sale",
                status=status,
                device_number=str(number)[:32] if number else None,
                local_time=_parse_time(raw.get("local_time")),
                received_at=utcnow(),
                payload=json.dumps(raw, ensure_ascii=False, default=str),
                code=code,
                message=message[:500],
            )
            s.add(op)
            s.flush()
            return result_of(op)
    except IntegrityError:
        return _existing(device_id, op_id)


def _existing(device_id: uuid.UUID, op_id: uuid.UUID) -> PushResult:
    s = new_session()
    try:
        op = s.get(SyncOperation, op_id)
        if op is None or op.device_id != device_id:
            return PushResult(
                id=op_id,
                status="rejected",
                code="duplicate_id",
                message="شناسه عملیات تکراری است",
                invoice_id=None,
                number=None,
            )
        return _stored(s, op)
    finally:
        s.close()


def push_one(device_id: uuid.UUID, raw: dict[str, Any]) -> PushResult:
    try:
        op_id = uuid.UUID(str(raw.get("id")))
    except ValueError:
        return PushResult(
            id=None,
            status="rejected",
            code="invalid",
            message="شناسه عملیات نامعتبر است",
            invoice_id=None,
            number=None,
        )
    s = new_session()
    try:
        if s.get(SyncOperation, op_id) is not None:
            return _existing(device_id, op_id)
    finally:
        s.close()

    try:
        op = OfflineOpIn.model_validate(raw)
    except ValidationError as e:
        where = ".".join(str(p) for p in e.errors()[0]["loc"]) if e.errors() else ""
        return _record(device_id, op_id, raw, "rejected", "invalid", f"داده نامعتبر: {where}")
    if op.sale.id != op.id:
        return _record(
            device_id, op_id, raw, "rejected", "invalid", "شناسه عملیات و فاکتور یکی نیست"
        )

    try:
        with unit_of_work() as s:
            d = s.get(Device, device_id)
            assert d is not None
            done = apply_sale(s, d, op.sale)
            rec = SyncOperation(
                id=op_id,
                device_id=device_id,
                op_type="sale",
                status="applied",
                device_number=op.sale.device_number,
                local_time=op.local_time,
                received_at=utcnow(),
                payload=json.dumps(raw, ensure_ascii=False, default=str),
                code=done.code,
                message=done.message,
                price_difference=done.price_difference,
                invoice_id=done.invoice.id,
            )
            s.add(rec)
            s.flush()
            return result_of(rec, done.invoice.number)
    except Rejected as e:
        return _record(device_id, op_id, raw, "rejected", e.code, e.message)
    except DomainError as e:
        return _record(device_id, op_id, raw, "conflict", e.code, e.message)
    except IntegrityError:
        # Either a concurrent resend of this operation, or data clashing with the server's.
        s = new_session()
        try:
            exists = s.get(SyncOperation, op_id) is not None
        finally:
            s.close()
        if exists:
            return _existing(device_id, op_id)
        return _record(
            device_id, op_id, raw, "conflict", "integrity", "ثبت با داده‌های سرور تعارض دارد"
        )


def push(device_id: uuid.UUID, ops: list[dict[str, Any]]) -> list[PushResult]:
    """Each operation in its own transaction: one conflict never holds back the rest."""
    results = [push_one(device_id, raw if isinstance(raw, dict) else {}) for raw in ops]
    with unit_of_work() as s:
        d = s.get(Device, device_id)
        if d is not None:
            d.last_sync_at = utcnow()
    return results
