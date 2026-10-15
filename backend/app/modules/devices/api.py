"""Device endpoints (/api/v1/devices).

Two audiences:
* users (session cookie + CSRF): register devices, configure printers, request prints;
* Device Agents (``Authorization: Bearer <device token>``, no cookie): pair, poll, report.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from flask import Blueprint, g, request
from flask.typing import ResponseReturnValue

from app.core.db import new_session, unit_of_work
from app.core.http import if_match, parse_body, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.openapi import doc
from app.core.ratelimit import limiter
from app.modules.devices.schemas import (
    DeviceConfigIn,
    DeviceCreateIn,
    DeviceOut,
    DrawerIn,
    JobOut,
    JobResultIn,
    PairIn,
    PairOut,
    PollIn,
    PollOut,
    PrintReceiptIn,
    RegisterDeviceOut,
)
from app.modules.devices.services import devices
from app.modules.iam.guard import current_actor, require, require_any

bp = Blueprint("devices", __name__)
MANAGE = "devices.manage"
P = ParamSpec("P")
R = TypeVar("R")


def _bearer() -> str | None:
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else None


def device_auth(fn: Callable[P, R]) -> Callable[P, R]:
    """Agent endpoints: device token only; a browser session never reaches them."""

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        s = new_session()
        try:
            g.device_id = devices.authenticate(s, _bearer()).id
        finally:
            s.close()
        return fn(*args, **kwargs)

    wrapper.device_auth = True  # type: ignore[attr-defined]
    return wrapper


# --- administration -------------------------------------------------------------


@bp.get("")
@require(MANAGE)
@doc("دستگاه‌ها (Device Agent) با وضعیت اتصال", response=[DeviceOut])
def list_devices() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(devices.list_devices(s, current_actor())))
    finally:
        s.close()


@bp.post("")
@require(MANAGE)
@doc(
    "تعریف دستگاه؛ کد جفت‌سازی فقط در همین پاسخ",
    body=DeviceCreateIn,
    response=DeviceOut,
    idempotent=True,
)
def create() -> ResponseReturnValue:
    data = parse_body(DeviceCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: devices.create(s, actor, data))


@bp.get("/<device_id>")
@require(MANAGE)
@doc("جزئیات دستگاه", response=DeviceOut)
def get(device_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(devices.get(s, current_actor(), parse_uuid(device_id)))
    finally:
        s.close()


@bp.put("/<device_id>")
@require(MANAGE)
@doc("تنظیم چاپگر و کشوی پول", body=DeviceConfigIn, response=DeviceOut, versioned=True)
def update(device_id: str) -> ResponseReturnValue:
    data = parse_body(DeviceConfigIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(devices.update(s, current_actor(), parse_uuid(device_id), data, version))


@bp.post("/<device_id>/pairing-code")
@require(MANAGE)
@doc("کد جفت‌سازی تازه (۱۵ دقیقه)", response=DeviceOut, versioned=True)
def pairing_code(device_id: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        return to_json(devices.new_pairing_code(s, current_actor(), parse_uuid(device_id), version))


@bp.post("/<device_id>/revoke")
@require(MANAGE)
@doc("ابطال دستگاه (توکن آن دیگر پذیرفته نمی‌شود)", response=DeviceOut, versioned=True)
def revoke(device_id: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        return to_json(devices.revoke(s, current_actor(), parse_uuid(device_id), version))


@bp.post("/<device_id>/test-print")
@require(MANAGE)
@doc("چاپ صفحه آزمایشی", response=JobOut)
def test_print(device_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(devices.test_print(s, current_actor(), parse_uuid(device_id)), 201)


@bp.get("/<device_id>/jobs")
@require(MANAGE)
@doc("آخرین کارهای دستگاه", response=[JobOut])
def device_jobs(device_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(devices.jobs(s, current_actor(), parse_uuid(device_id))))
    finally:
        s.close()


# --- POS ------------------------------------------------------------------------

POS = ("sales.pos.use", "sales.report.view", "sales.return.create")


@bp.get("/registers/<register_id>")
@require_any(*POS)
@doc("دستگاه صندوق: چاپگر و کشوی پول در دسترس است؟", response=RegisterDeviceOut)
def register_device(register_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(devices.for_register(s, current_actor(), parse_uuid(register_id)))
    finally:
        s.close()


@bp.post("/print-receipt")
@require_any(*POS)
@doc("چاپ فیش از طریق Device Agent صندوق فاکتور", body=PrintReceiptIn, response=JobOut)
def print_receipt() -> ResponseReturnValue:
    data = parse_body(PrintReceiptIn)
    with unit_of_work() as s:
        return to_json(devices.print_receipt(s, current_actor(), data), 201)


@bp.post("/open-drawer")
@require("sales.drawer.open")
@doc("باز کردن کشوی پول بدون فروش (ممیزی می‌شود)", body=DrawerIn, response=JobOut)
def open_drawer() -> ResponseReturnValue:
    data = parse_body(DrawerIn)
    with unit_of_work() as s:
        return to_json(devices.open_drawer(s, current_actor(), data), 201)


@bp.get("/jobs/<job_id>")
@require_any(MANAGE, *POS)
@doc("وضعیت یک کار چاپ", response=JobOut)
def job_status(job_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(devices.job_status(s, current_actor(), parse_uuid(job_id)))
    finally:
        s.close()


# --- agent ----------------------------------------------------------------------


@bp.post("/agent/pair")
@limiter.limit("10 per minute")
@doc(
    "جفت‌سازی Device Agent با کد یک‌بارمصرف (عمومی، محدود به ۱۰ بار در دقیقه)",
    body=PairIn,
    response=PairOut,
)
def agent_pair() -> ResponseReturnValue:
    data = parse_body(PairIn)
    with unit_of_work() as s:
        return to_json(devices.pair(s, data), 201)


@bp.post("/agent/poll")
@device_auth
@doc("دریافت تنظیمات و کار بعدی (Bearer توکن دستگاه)", body=PollIn, response=PollOut)
def agent_poll() -> ResponseReturnValue:
    data = parse_body(PollIn)
    with unit_of_work() as s:
        d = devices.authenticate(s, _bearer())
        return to_json(devices.poll(s, d, data))


@bp.post("/agent/jobs/<job_id>/result")
@device_auth
@doc("نتیجه اجرای کار (Bearer توکن دستگاه)", body=JobResultIn, response=JobOut)
def agent_result(job_id: str) -> ResponseReturnValue:
    data = parse_body(JobResultIn)
    with unit_of_work() as s:
        d = devices.authenticate(s, _bearer())
        return to_json(devices.report(s, d, parse_uuid(job_id), data))
