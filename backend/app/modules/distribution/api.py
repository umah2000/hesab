"""Field sales endpoints (/api/v1/distribution) — ADR-0018.

* ``/mobile/*``: the visitor app, signed in with a bearer access token
  (``distribution.visitor``). Orders and visits carry their own id, so a resend after a
  lost answer returns the same record instead of a second one.
* the rest: the back office (``distribution.manage``), within the user's branches.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date

from flask import Blueprint, Response, request
from flask.typing import ResponseReturnValue
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import new_session, unit_of_work
from app.core.http import if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.openapi import doc
from app.modules.distribution.schemas import (
    AssignedCustomerOut,
    AssignmentsIn,
    BootstrapOut,
    CandidateOut,
    DecisionIn,
    InvoiceOrderIn,
    OrderIn,
    OrderOut,
    OrderQuery,
    OrderSummaryOut,
    QuoteIn,
    QuoteOut,
    RejectIn,
    VisitIn,
    VisitorIn,
    VisitorOut,
    VisitorUpdateIn,
    VisitOut,
)
from app.modules.distribution.services import app as app_data
from app.modules.distribution.services import orders, visitors
from app.modules.iam.guard import current_actor, require

bp = Blueprint("distribution", __name__)
APP = "distribution.visitor"
MANAGE = "distribution.manage"


# --- the visitor app -------------------------------------------------------------------


@bp.get("/mobile/bootstrap")
@require(APP)
@doc("داده‌ی کار آفلاین اپلیکیشن ویزیتور (با If-None-Match پاسخ 304)", response=BootstrapOut)
def mobile_bootstrap() -> ResponseReturnValue:
    s = new_session()
    try:
        out = app_data.bootstrap(s, current_actor())
    finally:
        s.close()
    etag = f'"{out.version}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers={"ETag": etag})
    resp = to_json(out)
    resp.headers["ETag"] = etag
    return resp


@bp.post("/mobile/quote")
@require(APP)
@doc("قیمت قطعی سفارش از سرور (پیش از ثبت)", body=QuoteIn, response=QuoteOut)
def mobile_quote() -> ResponseReturnValue:
    data = parse_body(QuoteIn)
    s = new_session()
    try:
        return to_json(orders.quote(s, current_actor(), data))
    finally:
        s.close()


def _resend_safe(
    fn: Callable[[Session], tuple[BaseModel, bool]], read: Callable[[Session], BaseModel]
) -> Response:
    """Two copies of the same id racing: the loser reads what the winner stored."""
    try:
        with unit_of_work() as s:
            out, created = fn(s)
            return to_json(out, 201 if created else 200)
    except IntegrityError:
        s2 = new_session()
        try:
            return to_json(read(s2), 200)
        finally:
            s2.close()


@bp.post("/mobile/orders")
@require(APP)
@doc(
    "ثبت سفارش (شناسه از گوشی؛ ارسال دوباره همان سفارش را برمی‌گرداند)",
    body=OrderIn,
    response=OrderOut,
)
def mobile_order() -> ResponseReturnValue:
    data = parse_body(OrderIn)
    actor = current_actor()
    return _resend_safe(
        lambda s: orders.submit(s, actor, data), lambda s: orders.submit(s, actor, data)[0]
    )


@bp.get("/mobile/orders")
@require(APP)
@doc("سفارش‌های ۶۰ روز اخیر ویزیتور با وضعیت", response=[OrderOut])
def mobile_orders() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(orders.my_orders(s, current_actor())))
    finally:
        s.close()


@bp.post("/mobile/orders/<order_id>/cancel")
@require(APP)
@doc("لغو سفارش بررسی‌نشده توسط خود ویزیتور", response=OrderOut)
def mobile_cancel(order_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(orders.cancel_own(s, current_actor(), parse_uuid(order_id)))


@bp.post("/mobile/visits")
@require(APP)
@doc("ثبت بازدید (شناسه از گوشی)", body=VisitIn, response=VisitOut)
def mobile_visit() -> ResponseReturnValue:
    data = parse_body(VisitIn)
    actor = current_actor()
    return _resend_safe(
        lambda s: orders.record_visit(s, actor, data),
        lambda s: orders.record_visit(s, actor, data)[0],
    )


# --- back office ---------------------------------------------------------------------------


@bp.get("/visitors")
@require(MANAGE)
@doc("ویزیتورها", response=[VisitorOut])
def list_visitors() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(visitors.list_visitors(s, current_actor())))
    finally:
        s.close()


@bp.get("/candidates")
@require(MANAGE)
@doc("کاربران فعال با نقش ویزیتور (برای تعریف ویزیتور)", response=[CandidateOut])
def visitor_candidates() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(visitors.candidates(s)))
    finally:
        s.close()


@bp.post("/visitors")
@require(MANAGE)
@doc("تعریف ویزیتور برای کاربری با نقش ویزیتور", body=VisitorIn, response=VisitorOut)
def create_visitor() -> ResponseReturnValue:
    data = parse_body(VisitorIn)
    with unit_of_work() as s:
        return to_json(visitors.create(s, current_actor(), data), 201)


@bp.get("/visitors/<visitor_id>")
@require(MANAGE)
@doc("جزئیات ویزیتور", response=VisitorOut)
def get_visitor(visitor_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(visitors.get(s, current_actor(), parse_uuid(visitor_id)))
    finally:
        s.close()


@bp.put("/visitors/<visitor_id>")
@require(MANAGE)
@doc("ویرایش ویزیتور", body=VisitorUpdateIn, response=VisitorOut, versioned=True)
def update_visitor(visitor_id: str) -> ResponseReturnValue:
    data = parse_body(VisitorUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(visitors.update(s, current_actor(), parse_uuid(visitor_id), data, version))


@bp.get("/visitors/<visitor_id>/customers")
@require(MANAGE)
@doc("مشتریان تخصیص‌یافته با روز بازدید و اعتبار", response=[AssignedCustomerOut])
def visitor_customers(visitor_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(visitors.customers(s, current_actor(), parse_uuid(visitor_id))))
    finally:
        s.close()


@bp.put("/visitors/<visitor_id>/customers")
@require(MANAGE)
@doc("جایگزینی فهرست مشتریان ویزیتور", body=AssignmentsIn, response=[AssignedCustomerOut])
def assign_customers(visitor_id: str) -> ResponseReturnValue:
    data = parse_body(AssignmentsIn)
    with unit_of_work() as s:
        return to_json(list(visitors.assign(s, current_actor(), parse_uuid(visitor_id), data)))


@bp.get("/orders")
@require(MANAGE)
@doc("سفارش‌های ویزیتورها (status=open: بررسی‌نشده و تأییدشده)", response=[OrderSummaryOut])
def list_orders() -> ResponseReturnValue:
    q = parse_query(OrderQuery)
    s = new_session()
    try:
        return to_json(orders.list_orders(s, current_actor(), q))
    finally:
        s.close()


@bp.get("/orders/<order_id>")
@require(MANAGE)
@doc("جزئیات سفارش", response=OrderOut)
def get_order(order_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(orders.get(s, current_actor(), parse_uuid(order_id)))
    finally:
        s.close()


@bp.post("/orders/<order_id>/approve")
@require(MANAGE)
@doc("تأیید سفارش (کنترل سقف اعتبار)", body=DecisionIn, response=OrderOut, versioned=True)
def approve(order_id: str) -> ResponseReturnValue:
    data = parse_body(DecisionIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(orders.approve(s, current_actor(), parse_uuid(order_id), data, version))


@bp.post("/orders/<order_id>/reject")
@require(MANAGE)
@doc("رد سفارش با علت", body=RejectIn, response=OrderOut, versioned=True)
def reject(order_id: str) -> ResponseReturnValue:
    data = parse_body(RejectIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(orders.reject(s, current_actor(), parse_uuid(order_id), data, version))


@bp.post("/orders/<order_id>/invoice")
@require(MANAGE)
@doc(
    "صدور فاکتور فروش نسیه از سفارش تأییدشده (خروج کالا، سند، شماره)",
    body=InvoiceOrderIn,
    response=OrderOut,
    versioned=True,
)
def invoice(order_id: str) -> ResponseReturnValue:
    data = parse_body(InvoiceOrderIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(orders.invoice(s, current_actor(), parse_uuid(order_id), data, version))


@bp.post("/orders/<order_id>/deliver")
@require(MANAGE)
@doc("ثبت تحویل به مشتری", body=DecisionIn, response=OrderOut, versioned=True)
def deliver(order_id: str) -> ResponseReturnValue:
    data = parse_body(DecisionIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(orders.deliver(s, current_actor(), parse_uuid(order_id), data, version))


class VisitQuery(BaseModel):
    visitor_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


@bp.get("/visits")
@require(MANAGE)
@doc("بازدیدهای ثبت‌شده (۵۰۰ مورد آخر)", query=VisitQuery, response=[VisitOut])
def list_visits() -> ResponseReturnValue:
    q = parse_query(VisitQuery)
    s = new_session()
    try:
        rows: list[BaseModel] = list(
            orders.list_visits(s, current_actor(), q.visitor_id, q.date_from, q.date_to)
        )
        return to_json(rows)
    finally:
        s.close()
