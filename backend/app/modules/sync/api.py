"""Offline sync endpoints (/api/v1/sync) — ADR-0017, sync/protocol.md.

* Register agents (``Authorization: Bearer <device token>``): pull the snapshot, push
  the operations they queued while offline.
* People (session + CSRF): the inbox of conflicts and rejections, and resolving them.
"""

from __future__ import annotations

from flask import Blueprint, Response, g, request
from flask.typing import ResponseReturnValue

from app.core.db import new_session, unit_of_work
from app.core.http import if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.openapi import doc
from app.modules.devices.api import device_auth
from app.modules.devices.models import Device
from app.modules.iam.guard import current_actor, require
from app.modules.sync.schemas import (
    OperationOut,
    OperationQuery,
    PushIn,
    PushOut,
    ResolveIn,
    SnapshotOut,
)
from app.modules.sync.services import apply, operations
from app.modules.sync.services import snapshot as snap

bp = Blueprint("sync", __name__)
RESOLVE = "sync.resolve"


# --- agent ----------------------------------------------------------------------


@bp.get("/agent/snapshot")
@device_auth
@doc(
    "داده‌ی فروش آفلاین صندوق (Bearer توکن دستگاه؛ با If-None-Match پاسخ 304)",
    response=SnapshotOut,
)
def agent_snapshot() -> ResponseReturnValue:
    s = new_session()
    try:
        d = s.get(Device, g.device_id)
        assert d is not None
        out = snap.snapshot(s, d)
    finally:
        s.close()
    etag = f'"{out.version}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers={"ETag": etag})
    resp = to_json(out)
    resp.headers["ETag"] = etag
    return resp


@bp.post("/agent/push")
@device_auth
@doc(
    "ارسال فروش‌های آفلاین؛ هر عملیات جدا و یک‌بار اعمال می‌شود (Bearer توکن دستگاه)",
    body=PushIn,
    response=PushOut,
)
def agent_push() -> ResponseReturnValue:
    data = parse_body(PushIn)
    return to_json(PushOut(results=apply.push(g.device_id, data.ops)))


# --- people ---------------------------------------------------------------------


@bp.get("/operations")
@require(RESOLVE)
@doc("عملیات آفلاین رسیده از صندوق‌ها (status=open: تعارض‌ها و ردشده‌ها)", response=[OperationOut])
def list_operations() -> ResponseReturnValue:
    query = parse_query(OperationQuery)
    s = new_session()
    try:
        return to_json(operations.list_operations(s, current_actor(), query))
    finally:
        s.close()


@bp.get("/operations/<op_id>")
@require(RESOLVE)
@doc("جزئیات عملیات آفلاین", response=OperationOut)
def get_operation(op_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        op = operations.get(s, current_actor(), parse_uuid(op_id))
        return to_json(operations.operation_out(s, op))
    finally:
        s.close()


@bp.post("/operations/<op_id>/resolve")
@require(RESOLVE)
@doc(
    "رسیدگی به تعارض: ثبت با پذیرش مسئولیت یا کنار گذاشتن (ممیزی می‌شود)",
    body=ResolveIn,
    response=OperationOut,
    versioned=True,
)
def resolve(op_id: str) -> ResponseReturnValue:
    data = parse_body(ResolveIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(operations.resolve(s, current_actor(), parse_uuid(op_id), data, version))
