"""Report endpoints (/api/v1/reports). Each report checks its own permission."""

from __future__ import annotations

from flask import Blueprint, Response, request
from flask.typing import ResponseReturnValue
from pydantic import BaseModel
from sqlalchemy import select

from app.core import excel
from app.core.db import new_session, unit_of_work
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.http import parse_body, parse_query, parse_uuid, to_json
from app.core.openapi import doc
from app.modules.audit import service as audit
from app.modules.iam.guard import current_actor, require, require_any
from app.modules.organization.models import Organization
from app.modules.reports.registry import ALL_PERMISSIONS, REPORTS, allowed, catalog
from app.modules.reports.schemas import (
    Dashboard,
    DashboardQ,
    ReportInfo,
    ReportTable,
    SavedFilterIn,
    SavedFilterOut,
)
from app.modules.reports.services import export, saved
from app.modules.reports.services.sales import dashboard as build_dashboard

bp = Blueprint("reports", __name__)
ANY_REPORT = (*ALL_PERMISSIONS, "reports.dashboard")
EXPORT_ROWS = 50_000


@bp.get("")
@require_any(*ANY_REPORT)
@doc("فهرست گزارش‌هایی که کاربر مجاز است ببیند", response=[ReportInfo])
def list_reports() -> ResponseReturnValue:
    return to_json(list(catalog(current_actor())))


@bp.get("/dashboard")
@require("reports.dashboard")
@doc("داشبورد مدیریتی: فروش، سود، موجودی، طلب و بدهی", query=DashboardQ, response=Dashboard)
def dashboard() -> ResponseReturnValue:
    q = parse_query(DashboardQ)
    s = new_session()
    try:
        return to_json(build_dashboard(s, current_actor(), q))
    finally:
        s.close()


class SavedQuery(BaseModel):
    report: str | None = None


@bp.get("/saved-filters")
@require_any(*ANY_REPORT)
@doc("فیلترهای ذخیره‌شده من", query=SavedQuery, response=[SavedFilterOut])
def list_saved() -> ResponseReturnValue:
    q = parse_query(SavedQuery)
    s = new_session()
    try:
        return to_json(list(saved.list_filters(s, current_actor(), q.report)))
    finally:
        s.close()


@bp.post("/saved-filters")
@require_any(*ANY_REPORT)
@doc("ذخیره فیلتر گزارش", body=SavedFilterIn, response=SavedFilterOut)
def create_saved() -> ResponseReturnValue:
    data = parse_body(SavedFilterIn)
    with unit_of_work() as s:
        return to_json(saved.create(s, current_actor(), data), 201)


@bp.delete("/saved-filters/<filter_id>")
@require_any(*ANY_REPORT)
@doc("حذف فیلتر ذخیره‌شده")
def delete_saved(filter_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        saved.delete(s, current_actor(), parse_uuid(filter_id))
    return Response(status=204)


@bp.get("/<key>")
@require_any(*ALL_PERMISSIONS)
@doc("اجرای یک گزارش؛ ‎?format=xlsx‎ خروجی Excel", response=ReportTable)
def run(key: str) -> ResponseReturnValue:
    rep = REPORTS.get(key)
    actor = current_actor()
    if rep is None:
        raise NotFoundError("گزارش یافت نشد")
    if not allowed(actor, rep):
        raise PermissionDeniedError("شما مجوز این گزارش را ندارید")
    params = parse_query(rep.query)
    as_excel = request.args.get("format") == "xlsx"
    if as_excel:
        params = params.model_copy(update={"page": 1, "page_size": EXPORT_ROWS})
    s = new_session()
    try:
        table = rep.run(s, actor, params)
        if not as_excel:
            return to_json(table)
        org = s.scalar(select(Organization))
        currency = org.display_currency if org else "IRT"
    finally:
        s.close()
    shown = {k: v for k, v in request.args.items() if k in rep.filters}
    with unit_of_work() as s:
        audit.record(
            s,
            "reports.exported",
            user_id=actor.user_id,
            entity_type="report",
            entity_id=key,
            data=shown,
        )
    filters = "، ".join(f"{k}={v}" for k, v in shown.items()) or "بدون فیلتر"
    return Response(
        export.xlsx(table, currency, filters),
        mimetype=excel.XLSX,
        headers={"Content-Disposition": f"attachment; filename=nextcam-{key}.xlsx"},
    )
