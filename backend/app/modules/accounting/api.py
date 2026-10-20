"""Accounting endpoints. Thin: parse → service (one unit of work) → serialize."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import ParamSpec, TypeVar

from flask import Blueprint, request
from flask.typing import ResponseReturnValue
from pydantic import BaseModel, Field

from app.core.db import new_session, unit_of_work
from app.core.http import if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.openapi import doc
from app.modules.accounting.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountUpdateIn,
    DetailAccountCreateIn,
    DetailAccountOut,
    DetailAccountUpdateIn,
    FiscalYearCreateIn,
    FiscalYearOut,
    LedgerOut,
    LedgerQuery,
    PeriodLockIn,
    PostingRuleIn,
    PostingRuleOut,
    ReverseIn,
    TrialBalanceOut,
    TrialBalanceQuery,
    VoucherIn,
    VoucherOut,
    VoucherQuery,
    VoucherSummaryOut,
)
from app.modules.accounting.services import chart, closing, fiscal, posting, reports, vouchers
from app.modules.iam.guard import current_actor, require, require_any

P = ParamSpec("P")
R = TypeVar("R")

bp = Blueprint("accounting", __name__)

# Anyone working with accounting may read the chart and vouchers.
READ = (
    "accounting.account.manage",
    "accounting.voucher.create",
    "accounting.voucher.finalize",
    "accounting.report.view",
)


def _read(fn: Callable[P, R]) -> Callable[P, R]:
    return require_any(*READ)(fn)


# --- chart ------------------------------------------------------------------


@bp.get("/accounts")
@_read
@doc("کدینگ حساب‌ها (مرتب بر اساس کد)", response=[AccountOut])
def list_accounts() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(chart.list_accounts(s)))
    finally:
        s.close()


@bp.post("/accounts")
@require("accounting.account.manage")
@doc("ایجاد حساب", body=AccountCreateIn, response=AccountOut, idempotent=True)
def create_account() -> ResponseReturnValue:
    data = parse_body(AccountCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: chart.create_account(s, actor, data))


@bp.patch("/accounts/<account_id>")
@require("accounting.account.manage")
@doc("ویرایش حساب", body=AccountUpdateIn, response=AccountOut, versioned=True)
def update_account(account_id: str) -> ResponseReturnValue:
    data = parse_body(AccountUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(
            chart.update_account(s, current_actor(), parse_uuid(account_id), data, version)
        )


@bp.get("/detail-accounts")
@_read
@doc("حساب‌های تفصیلی", response=[DetailAccountOut])
def list_details() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(
            list(chart.list_details(s, (request.args.get("q") or "").strip()[:50] or None))
        )
    finally:
        s.close()


@bp.post("/detail-accounts")
@require("accounting.account.manage")
@doc("ایجاد حساب تفصیلی", body=DetailAccountCreateIn, response=DetailAccountOut, idempotent=True)
def create_detail() -> ResponseReturnValue:
    data = parse_body(DetailAccountCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: chart.create_detail(s, actor, data))


@bp.patch("/detail-accounts/<detail_id>")
@require("accounting.account.manage")
@doc("ویرایش حساب تفصیلی", body=DetailAccountUpdateIn, response=DetailAccountOut, versioned=True)
def update_detail(detail_id: str) -> ResponseReturnValue:
    data = parse_body(DetailAccountUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(
            chart.update_detail(s, current_actor(), parse_uuid(detail_id), data, version)
        )


# --- fiscal -----------------------------------------------------------------


@bp.get("/fiscal-years")
@_read
@doc("سال‌های مالی و دوره‌ها", response=[FiscalYearOut])
def list_years() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(fiscal.list_years(s)))
    finally:
        s.close()


@bp.post("/fiscal-years")
@require("accounting.fiscal.close")
@doc("تعریف سال مالی (سال شمسی)", body=FiscalYearCreateIn, response=FiscalYearOut, idempotent=True)
def create_year() -> ResponseReturnValue:
    data = parse_body(FiscalYearCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: fiscal.create_year(s, actor, data.jalali_year))


@bp.put("/fiscal-periods/<period_id>/lock")
@require("accounting.fiscal.close")
@doc("قفل/بازگشایی دوره", body=PeriodLockIn, response=FiscalYearOut, versioned=True)
def lock_period(period_id: str) -> ResponseReturnValue:
    data = parse_body(PeriodLockIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(
            fiscal.set_period_lock(
                s, current_actor(), parse_uuid(period_id), data.is_locked, version
            )
        )


@bp.post("/fiscal-years/<fy_id>/close")
@require("accounting.fiscal.close")
@doc("بستن سال مالی: بستن حساب‌های موقت، اختتامیه و افتتاحیه سال بعد")
def close_year(fy_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(closing.close_year(s, current_actor(), parse_uuid(fy_id)))


# --- vouchers ---------------------------------------------------------------


@bp.get("/vouchers")
@_read
@doc("فهرست اسناد", query=VoucherQuery, response=VoucherSummaryOut)
def list_vouchers() -> ResponseReturnValue:
    q = parse_query(VoucherQuery)
    s = new_session()
    try:
        return to_json(vouchers.list_vouchers(s, current_actor(), q))
    finally:
        s.close()


@bp.get("/vouchers/<voucher_id>")
@_read
@doc("جزئیات سند", response=VoucherOut)
def get_voucher(voucher_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        v = vouchers.get_voucher(s, current_actor(), parse_uuid(voucher_id))
        return to_json(vouchers.voucher_out(s, v))
    finally:
        s.close()


@bp.post("/vouchers")
@require("accounting.voucher.create")
@doc("ثبت سند پیش‌نویس", body=VoucherIn, response=VoucherOut, idempotent=True)
def create_voucher() -> ResponseReturnValue:
    data = parse_body(VoucherIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: vouchers.create_draft(s, actor, data))


@bp.put("/vouchers/<voucher_id>")
@require("accounting.voucher.create")
@doc("ویرایش سند پیش‌نویس", body=VoucherIn, response=VoucherOut, versioned=True)
def update_voucher(voucher_id: str) -> ResponseReturnValue:
    data = parse_body(VoucherIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(
            vouchers.update_draft(s, current_actor(), parse_uuid(voucher_id), data, version)
        )


@bp.delete("/vouchers/<voucher_id>")
@require("accounting.voucher.create")
@doc("حذف سند پیش‌نویس (سند قطعی حذف نمی‌شود)", versioned=True)
def delete_voucher(voucher_id: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        vouchers.delete_draft(s, current_actor(), parse_uuid(voucher_id), version)
    return to_json({"status": "ok"})


@bp.post("/vouchers/<voucher_id>/finalize")
@require("accounting.voucher.finalize")
@doc("قطعی کردن سند و تخصیص شماره", response=VoucherOut, versioned=True)
def finalize_voucher(voucher_id: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        return to_json(vouchers.finalize(s, current_actor(), parse_uuid(voucher_id), version))


@bp.post("/vouchers/<voucher_id>/reverse")
@require("accounting.voucher.reverse")
@doc("صدور سند برگشت برای سند قطعی", body=ReverseIn, response=VoucherOut, versioned=True)
def reverse_voucher(voucher_id: str) -> ResponseReturnValue:
    data = parse_body(ReverseIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(
            vouchers.reverse(
                s,
                current_actor(),
                parse_uuid(voucher_id),
                version,
                data.document_date,
                data.description,
            ),
            status=201,
        )


# --- posting rules ----------------------------------------------------------


@bp.get("/posting-rules")
@require_any("accounting.account.manage", "accounting.report.view")
@doc("قواعد ثبت خودکار", response=[PostingRuleOut])
def list_rules() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(posting.list_rules(s)))
    finally:
        s.close()


@bp.put("/posting-rules")
@require("accounting.account.manage")
@doc("تعیین حساب برای یک نقش ثبت خودکار", body=PostingRuleIn, response=[PostingRuleOut])
def set_rule() -> ResponseReturnValue:
    data = parse_body(PostingRuleIn)
    with unit_of_work() as s:
        return to_json(list(posting.set_rule(s, current_actor(), data)))


# --- reports ----------------------------------------------------------------


@bp.get("/reports/trial-balance")
@require("accounting.report.view")
@doc("تراز آزمایشی", query=TrialBalanceQuery, response=TrialBalanceOut)
def trial_balance() -> ResponseReturnValue:
    q = parse_query(TrialBalanceQuery)
    s = new_session()
    try:
        return to_json(reports.trial_balance(s, current_actor(), q))
    finally:
        s.close()


@bp.get("/reports/ledger")
@require("accounting.report.view")
@doc("دفتر کل / معین با مانده جاری", query=LedgerQuery, response=LedgerOut)
def ledger() -> ResponseReturnValue:
    q = parse_query(LedgerQuery)
    s = new_session()
    try:
        return to_json(reports.ledger(s, current_actor(), q))
    finally:
        s.close()


class JournalQuery(BaseModel):
    fiscal_year_id: str
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


@bp.get("/reports/journal")
@require("accounting.report.view")
@doc("دفتر روزنامه", query=JournalQuery, response=VoucherOut)
def journal() -> ResponseReturnValue:
    q = parse_query(JournalQuery)
    s = new_session()
    try:
        return to_json(
            reports.journal(
                s,
                current_actor(),
                parse_uuid(q.fiscal_year_id),
                q.date_from,
                q.date_to,
                q.page,
                q.page_size,
            )
        )
    finally:
        s.close()
