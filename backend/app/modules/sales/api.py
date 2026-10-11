"""Sales / POS endpoints (/api/v1/sales) and card-reader endpoints (/api/v1/payments)."""

from __future__ import annotations

from datetime import date

from flask import Blueprint
from flask.typing import ResponseReturnValue
from pydantic import BaseModel, Field

from app.core.db import new_session, unit_of_work
from app.core.http import Page, if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.openapi import doc
from app.core.ratelimit import limiter
from app.modules.iam.guard import current_actor, require, require_any
from app.modules.inventory.services.stock import tehran_today
from app.modules.organization.models import Branch
from app.modules.sales.schemas import (
    ApprovalIn,
    ApprovalOut,
    CartIn,
    CheckoutIn,
    DailyReportOut,
    HoldIn,
    InvoiceOut,
    InvoiceQuery,
    InvoiceSummaryOut,
    LineRemovalIn,
    PromotionIn,
    PromotionOut,
    QuoteOut,
    RegisterStateOut,
    ReturnIn,
    ShiftCloseIn,
    ShiftOpenIn,
    ShiftOut,
    ShiftReportOut,
    TerminalResolveIn,
    TerminalStartIn,
    TerminalTxOut,
)
from app.modules.sales.services import (
    approvals,
    invoices,
    pricing,
    promotions,
    shifts,
    terminal,
)

bp = Blueprint("sales", __name__)
payments_bp = Blueprint("payments", __name__)

POS = ("sales.pos.use",)
VIEW = ("sales.pos.use", "sales.report.view", "sales.return.create")


# --- register / shifts ------------------------------------------------------


@bp.get("/registers/<register_id>/state")
@require_any(*VIEW)
@doc("وضعیت صندوق برای شروع کار POS", response=RegisterStateOut)
def register_state(register_id: str) -> ResponseReturnValue:
    actor = current_actor()
    s = new_session()
    try:
        reg, wh = pricing.register_and_warehouse(s, parse_uuid(register_id), actor.branch_ids)
        org = pricing.organization(s)
        branch = s.get(Branch, reg.branch_id)
        mine = shifts.open_shift_of(s, actor.user_id)
        other = shifts.open_shift_on(s, reg.id)
        other_user = None
        if other is not None and other.user_id != actor.user_id:
            other_user = shifts.shift_out(s, other).user_name
        return to_json(
            RegisterStateOut(
                cash_register_id=reg.id,
                register_name=reg.name,
                branch_id=reg.branch_id,
                branch_name=branch.name if branch else "",
                warehouse_id=wh.id,
                shift=shifts.shift_out(s, mine)
                if mine and mine.cash_register_id == reg.id
                else None,
                other_shift_user=other_user,
                held_count=len(invoices.list_held(s, actor, reg.id)),
                display_currency=org.display_currency,  # type: ignore[arg-type]
                receipt_header=org.receipt_header,
                receipt_footer=org.receipt_footer,
                organization_name=org.name,
                terminal=terminal.info(),
                permissions=sorted(
                    p for p in actor.permissions if p.startswith(("sales.", "payments."))
                ),
            )
        )
    finally:
        s.close()


@bp.post("/shifts/open")
@require("sales.shift.open")
@doc("باز کردن شیفت صندوق", body=ShiftOpenIn, response=ShiftOut, idempotent=True)
def open_shift() -> ResponseReturnValue:
    data = parse_body(ShiftOpenIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: shifts.open_shift(s, actor, data))


@bp.post("/shifts/<shift_id>/close")
@require("sales.shift.close")
@doc("بستن شیفت با شمارش وجه نقد", body=ShiftCloseIn, response=ShiftOut, versioned=True)
def close_shift(shift_id: str) -> ResponseReturnValue:
    data = parse_body(ShiftCloseIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(shifts.close_shift(s, current_actor(), parse_uuid(shift_id), data, version))


class ShiftQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=30, ge=1, le=200)
    cash_register_id: str | None = None


@bp.get("/shifts")
@require_any(*VIEW)
@doc("فهرست شیفت‌ها", query=ShiftQuery, response=ShiftOut)
def list_shifts() -> ResponseReturnValue:
    q = parse_query(ShiftQuery)
    s = new_session()
    try:
        rows, total = shifts.list_shifts(
            s,
            current_actor(),
            parse_uuid(q.cash_register_id) if q.cash_register_id else None,
            q.page,
            q.page_size,
        )
        return to_json(Page(items=rows, total=total, page=q.page, page_size=q.page_size))
    finally:
        s.close()


@bp.get("/shifts/<shift_id>/report")
@require_any(*VIEW)
@doc("گزارش شیفت", response=ShiftReportOut)
def shift_report(shift_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(shifts.report(s, current_actor(), parse_uuid(shift_id)))
    finally:
        s.close()


# --- cart -------------------------------------------------------------------


@bp.post("/quote")
@require_any(*POS)
@doc("محاسبه قیمت، تخفیف و مالیات سبد (بدون ثبت)", body=CartIn, response=QuoteOut)
def quote() -> ResponseReturnValue:
    data = parse_body(CartIn)
    actor = current_actor()
    s = new_session()
    try:
        _, wh = pricing.register_and_warehouse(s, data.cash_register_id, actor.branch_ids)
        return to_json(pricing.price_cart(s, data, warehouse_id=wh.id, today=tehran_today()).out())
    finally:
        s.close()


@bp.post("/invoices")
@require_any(*POS)
@doc(
    "ثبت قطعی فروش (فروش + انبار + سند در یک تراکنش)",
    body=CheckoutIn,
    response=InvoiceOut,
    idempotent=True,
)
def checkout() -> ResponseReturnValue:
    data = parse_body(CheckoutIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: invoices.checkout(s, actor, data))


@bp.get("/invoices")
@require_any(*VIEW)
@doc("فهرست فاکتورها", query=InvoiceQuery, response=InvoiceSummaryOut)
def list_invoices() -> ResponseReturnValue:
    q = parse_query(InvoiceQuery)
    s = new_session()
    try:
        return to_json(invoices.list_invoices(s, current_actor(), q))
    finally:
        s.close()


@bp.get("/invoices/<invoice_id>")
@require_any(*VIEW)
@doc("جزئیات فاکتور", response=InvoiceOut)
def get_invoice(invoice_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(invoices.get_invoice(s, current_actor(), parse_uuid(invoice_id)))
    finally:
        s.close()


@bp.post("/invoices/<invoice_id>/returns")
@require("sales.return.create")
@doc("برگشت از فروش", body=ReturnIn, response=InvoiceOut, idempotent=True)
def create_return(invoice_id: str) -> ResponseReturnValue:
    data = parse_body(ReturnIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(
            s, actor.user_id, lambda: invoices.create_return(s, actor, parse_uuid(invoice_id), data)
        )


@bp.post("/held")
@require_any(*POS)
@doc("تعلیق فاکتور", body=HoldIn, response=InvoiceOut, idempotent=True)
def hold() -> ResponseReturnValue:
    data = parse_body(HoldIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: invoices.hold(s, actor, data))


class HeldQuery(BaseModel):
    cash_register_id: str


@bp.get("/held")
@require_any(*POS)
@doc("فاکتورهای معلق شعبه", query=HeldQuery, response=[InvoiceSummaryOut])
def list_held() -> ResponseReturnValue:
    q = parse_query(HeldQuery)
    s = new_session()
    try:
        return to_json(list(invoices.list_held(s, current_actor(), parse_uuid(q.cash_register_id))))
    finally:
        s.close()


@bp.post("/held/<invoice_id>/recall")
@require_any(*POS)
@doc("بازیابی فاکتور معلق", response=InvoiceOut)
def recall(invoice_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(invoices.recall(s, current_actor(), parse_uuid(invoice_id)))


@bp.post("/approvals")
@require_any(*POS)
@limiter.limit("10 per minute")
@doc("تأیید سرپرست روی صندوق (رمز سرپرست)", body=ApprovalIn, response=ApprovalOut)
def approve() -> ResponseReturnValue:
    data = parse_body(ApprovalIn)
    return to_json(approvals.grant(current_actor(), data), 201)


@bp.post("/line-removals")
@require_any(*POS)
@doc("ثبت حذف ردیف اسکن‌شده (با مجوز یا تأیید سرپرست)", body=LineRemovalIn)
def line_removal() -> ResponseReturnValue:
    data = parse_body(LineRemovalIn)
    with unit_of_work() as s:
        return to_json(invoices.record_line_removal(s, current_actor(), data), 201)


# --- promotions -------------------------------------------------------------


@bp.get("/promotions")
@require_any("inventory.price.manage", "sales.report.view")
@doc("پروموشن‌ها", response=[PromotionOut])
def list_promotions() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(promotions.list_promotions(s)))
    finally:
        s.close()


@bp.post("/promotions")
@require("inventory.price.manage")
@doc("تعریف پروموشن", body=PromotionIn, response=PromotionOut, idempotent=True)
def create_promotion() -> ResponseReturnValue:
    data = parse_body(PromotionIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: promotions.save(s, actor, data))


@bp.put("/promotions/<promotion_id>")
@require("inventory.price.manage")
@doc("ویرایش پروموشن", body=PromotionIn, response=PromotionOut, versioned=True)
def update_promotion(promotion_id: str) -> ResponseReturnValue:
    data = parse_body(PromotionIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(promotions.save(s, current_actor(), data, parse_uuid(promotion_id), version))


# --- reports ----------------------------------------------------------------


class DailyQuery(BaseModel):
    day: date | None = Field(default=None, alias="date")
    branch_id: str | None = None


@bp.get("/reports/daily")
@require("sales.report.view")
@doc("گزارش فروش روزانه", query=DailyQuery, response=DailyReportOut)
def daily() -> ResponseReturnValue:
    q = parse_query(DailyQuery)
    s = new_session()
    try:
        return to_json(
            invoices.daily_report(
                s,
                current_actor(),
                q.day or tehran_today(),
                parse_uuid(q.branch_id) if q.branch_id else None,
            )
        )
    finally:
        s.close()


# --- card reader (/api/v1/payments) -----------------------------------------


@payments_bp.post("/terminal-transactions")
@require("sales.payment.card")
@doc("ارسال مبلغ به کارت‌خوان", body=TerminalStartIn, response=TerminalTxOut)
def terminal_start() -> ResponseReturnValue:
    data = parse_body(TerminalStartIn)
    with unit_of_work() as s:
        return to_json(terminal.start(s, current_actor(), data), 201)


@payments_bp.get("/terminal-transactions")
@require("payments.reconcile")
@doc("تراکنش‌های نامشخص کارت‌خوان", response=[TerminalTxOut])
def terminal_unresolved() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(terminal.list_unresolved(s, current_actor())))
    finally:
        s.close()


@payments_bp.get("/terminal-transactions/<tx_id>")
@require_any("sales.payment.card", "payments.reconcile")
@doc("وضعیت تراکنش کارت‌خوان", response=TerminalTxOut)
def terminal_get(tx_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(terminal.get(s, current_actor(), parse_uuid(tx_id)))
    finally:
        s.close()


@payments_bp.post("/terminal-transactions/<tx_id>/inquire")
@require_any("sales.payment.card", "payments.reconcile")
@doc("استعلام تراکنش نامشخص", response=TerminalTxOut)
def terminal_inquire(tx_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(terminal.inquire(s, current_actor(), parse_uuid(tx_id)))


@payments_bp.post("/terminal-transactions/<tx_id>/resolve")
@require("payments.reconcile")
@doc("تطبیق دستی با گزارش بانک", body=TerminalResolveIn, response=TerminalTxOut, versioned=True)
def terminal_resolve(tx_id: str) -> ResponseReturnValue:
    data = parse_body(TerminalResolveIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(terminal.resolve(s, current_actor(), parse_uuid(tx_id), data, version))
