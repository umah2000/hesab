"""Purchasing endpoints (/api/v1/purchasing): orders, invoices, returns, price history, dues."""

from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, Response
from flask.typing import ResponseReturnValue
from pydantic import BaseModel, Field

from app.core.db import new_session, unit_of_work
from app.core.http import if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.openapi import doc
from app.modules.iam.guard import current_actor, require
from app.modules.inventory.services.stock import tehran_today
from app.modules.purchasing.schemas import (
    DueOut,
    InvoiceIn,
    InvoiceOut,
    InvoiceQuery,
    InvoiceSummary,
    OrderIn,
    OrderOut,
    OrderQuery,
    OrderSummary,
    PriceHistoryOut,
    ReturnIn,
)
from app.modules.purchasing.services import invoices, orders

bp = Blueprint("purchasing", __name__)
PERM = "purchasing.manage"


# --- orders -----------------------------------------------------------------


@bp.get("/orders")
@require(PERM)
@doc("سفارش‌های خرید", query=OrderQuery, response=OrderSummary)
def list_orders() -> ResponseReturnValue:
    q = parse_query(OrderQuery)
    s = new_session()
    try:
        return to_json(orders.list_orders(s, current_actor(), q))
    finally:
        s.close()


@bp.post("/orders")
@require(PERM)
@doc("ثبت سفارش خرید (پیش‌نویس)", body=OrderIn, response=OrderOut, idempotent=True)
def create_order() -> ResponseReturnValue:
    data = parse_body(OrderIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: orders.create(s, actor, data))


@bp.get("/orders/<order_id>")
@require(PERM)
@doc("جزئیات سفارش خرید با مقدار دریافت‌شده", response=OrderOut)
def get_order(order_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(orders.get(s, current_actor(), parse_uuid(order_id)))
    finally:
        s.close()


@bp.put("/orders/<order_id>")
@require(PERM)
@doc("ویرایش سفارش پیش‌نویس", body=OrderIn, response=OrderOut, versioned=True)
def update_order(order_id: str) -> ResponseReturnValue:
    data = parse_body(OrderIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(orders.update(s, current_actor(), parse_uuid(order_id), data, version))


def _order_action(order_id: str, action: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        return to_json(orders.set_status(s, current_actor(), parse_uuid(order_id), action, version))


@bp.post("/orders/<order_id>/approve")
@require(PERM)
@doc("تأیید سفارش (شماره می‌گیرد)", response=OrderOut, versioned=True)
def approve_order(order_id: str) -> ResponseReturnValue:
    return _order_action(order_id, "approve")


@bp.post("/orders/<order_id>/cancel")
@require(PERM)
@doc("لغو سفارش دریافت‌نشده", response=OrderOut, versioned=True)
def cancel_order(order_id: str) -> ResponseReturnValue:
    return _order_action(order_id, "cancel")


@bp.post("/orders/<order_id>/close")
@require(PERM)
@doc("بستن سفارش با دریافت ناقص", response=OrderOut, versioned=True)
def close_order(order_id: str) -> ResponseReturnValue:
    return _order_action(order_id, "close")


# --- invoices ---------------------------------------------------------------


@bp.get("/invoices")
@require(PERM)
@doc("فاکتورهای خرید و برگشت از خرید", query=InvoiceQuery, response=InvoiceSummary)
def list_invoices() -> ResponseReturnValue:
    q = parse_query(InvoiceQuery)
    s = new_session()
    try:
        return to_json(invoices.list_invoices(s, current_actor(), q))
    finally:
        s.close()


@bp.post("/invoices")
@require(PERM)
@doc("ثبت پیش‌نویس فاکتور خرید", body=InvoiceIn, response=InvoiceOut, idempotent=True)
def create_invoice() -> ResponseReturnValue:
    data = parse_body(InvoiceIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: invoices.create(s, actor, data))


@bp.get("/invoices/<invoice_id>")
@require(PERM)
@doc("جزئیات فاکتور خرید", response=InvoiceOut)
def get_invoice(invoice_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(invoices.get(s, current_actor(), parse_uuid(invoice_id)))
    finally:
        s.close()


@bp.put("/invoices/<invoice_id>")
@require(PERM)
@doc("ویرایش پیش‌نویس فاکتور خرید", body=InvoiceIn, response=InvoiceOut, versioned=True)
def update_invoice(invoice_id: str) -> ResponseReturnValue:
    data = parse_body(InvoiceIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(invoices.update(s, current_actor(), parse_uuid(invoice_id), data, version))


@bp.delete("/invoices/<invoice_id>")
@require(PERM)
@doc("حذف پیش‌نویس فاکتور خرید", versioned=True)
def delete_invoice(invoice_id: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        invoices.delete(s, current_actor(), parse_uuid(invoice_id), version)
    return Response(status=204)


@bp.post("/invoices/<invoice_id>/finalize")
@require(PERM)
@doc("قطعی کردن فاکتور خرید: ورود کالا و سند حسابداری", response=InvoiceOut, versioned=True)
def finalize_invoice(invoice_id: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        return to_json(invoices.finalize(s, current_actor(), parse_uuid(invoice_id), version))


@bp.post("/invoices/<invoice_id>/returns")
@require(PERM)
@doc("برگشت از خرید (قطعی)", body=ReturnIn, response=InvoiceOut, idempotent=True)
def create_return(invoice_id: str) -> ResponseReturnValue:
    data = parse_body(ReturnIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(
            s, actor.user_id, lambda: invoices.create_return(s, actor, parse_uuid(invoice_id), data)
        )


@bp.get("/items/<item_id>/price-history")
@require(PERM)
@doc("سابقه قیمت خرید کالا", response=[PriceHistoryOut])
def price_history(item_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(invoices.price_history(s, parse_uuid(item_id))))
    finally:
        s.close()


class DueQuery(BaseModel):
    days: int = Field(default=7, ge=0, le=365)


@bp.get("/dues")
@require(PERM)
@doc("بدهی‌های سررسیده و نزدیک به سررسید به تأمین‌کنندگان", query=DueQuery, response=[DueOut])
def dues() -> ResponseReturnValue:
    q = parse_query(DueQuery)
    today: date = tehran_today()
    s = new_session()
    try:
        return to_json(
            list(invoices.due_list(s, current_actor(), today + timedelta(days=q.days), today))
        )
    finally:
        s.close()
