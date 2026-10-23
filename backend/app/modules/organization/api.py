from __future__ import annotations

from flask import Blueprint, request
from flask.typing import ResponseReturnValue

from app.core.db import new_session, unit_of_work
from app.core.errors import DomainError
from app.core.http import if_match, parse_body, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.images import MAX_UPLOAD
from app.core.openapi import doc
from app.modules.iam.guard import current_actor, login_required, require
from app.modules.organization import services
from app.modules.organization.schemas import (
    BranchCreateIn,
    BranchOut,
    BranchUpdateIn,
    CashRegisterCreateIn,
    CashRegisterOut,
    CashRegisterUpdateIn,
    OrganizationOut,
    OrganizationUpdateIn,
)

bp = Blueprint("organization", __name__)


@bp.get("/settings")
@login_required
@doc("تنظیمات سازمان", response=OrganizationOut)
def get_settings() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(services.get_organization(s))
    finally:
        s.close()


@bp.put("/settings")
@require("settings.manage")
@doc("ویرایش تنظیمات سازمان", body=OrganizationUpdateIn, response=OrganizationOut, versioned=True)
def update_settings() -> ResponseReturnValue:
    data = parse_body(OrganizationUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(services.update_organization(s, current_actor(), data, version))


@bp.post("/logo")
@require("settings.manage")
@doc("بارگذاری لوگوی سازمان (multipart، فیلد file؛ JPEG/PNG/WebP)", response=OrganizationOut)
def upload_logo() -> ResponseReturnValue:
    request.max_content_length = MAX_UPLOAD + 64 * 1024
    f = request.files.get("file")
    if f is None:
        raise DomainError("فایل لوگو را انتخاب کنید", code="file_required")
    data = f.read()
    with unit_of_work() as s:
        return to_json(services.set_logo(s, current_actor(), data))


@bp.delete("/logo")
@require("settings.manage")
@doc("حذف لوگوی سازمان", response=OrganizationOut)
def delete_logo() -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(services.remove_logo(s, current_actor()))


@bp.get("/branches")
@login_required
@doc("فهرست شعب در محدوده کاربر", response=[BranchOut])
def list_branches() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(services.list_branches(s, current_actor())))
    finally:
        s.close()


@bp.post("/branches")
@require("branches.manage")
@doc("ایجاد شعبه", body=BranchCreateIn, response=BranchOut, idempotent=True)
def create_branch() -> ResponseReturnValue:
    data = parse_body(BranchCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: services.create_branch(s, actor, data))


@bp.patch("/branches/<branch_id>")
@require("branches.manage")
@doc("ویرایش شعبه", body=BranchUpdateIn, response=BranchOut, versioned=True)
def update_branch(branch_id: str) -> ResponseReturnValue:
    data = parse_body(BranchUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(
            services.update_branch(s, current_actor(), parse_uuid(branch_id), data, version)
        )


@bp.get("/branches/<branch_id>/cash-registers")
@login_required
@doc("صندوق‌های یک شعبه", response=[CashRegisterOut])
def list_registers(branch_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(services.list_registers(s, current_actor(), parse_uuid(branch_id))))
    finally:
        s.close()


@bp.post("/cash-registers")
@require("branches.manage")
@doc("ایجاد صندوق", body=CashRegisterCreateIn, response=CashRegisterOut, idempotent=True)
def create_register() -> ResponseReturnValue:
    data = parse_body(CashRegisterCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: services.create_register(s, actor, data))


@bp.patch("/cash-registers/<register_id>")
@require("branches.manage")
@doc("ویرایش صندوق", body=CashRegisterUpdateIn, response=CashRegisterOut, versioned=True)
def update_register(register_id: str) -> ResponseReturnValue:
    data = parse_body(CashRegisterUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(
            services.update_register(s, current_actor(), parse_uuid(register_id), data, version)
        )
