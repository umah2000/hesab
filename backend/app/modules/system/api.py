"""System endpoints: liveness and readiness (database reachability)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint, current_app, jsonify
from flask.typing import ResponseReturnValue
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import new_session, unit_of_work
from app.core.errors import DomainError
from app.core.openapi import doc
from app.modules.audit import service as audit
from app.modules.iam.guard import current_actor, require, require_any
from app.modules.system import backup

bp = Blueprint("system", __name__)


@bp.get("/health")
def health() -> ResponseReturnValue:
    return jsonify({"status": "ok"})


@bp.get("/ready")
def ready() -> ResponseReturnValue:
    try:
        with current_app.extensions["db_engine"].connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        current_app.logger.warning("database not reachable")
        return jsonify({"status": "unavailable", "database": "down"}), 503
    return jsonify({"status": "ok", "database": "up"})


# --- backups ----------------------------------------------------------------


def _engine() -> Engine:
    engine: Engine = current_app.extensions["db_engine"]
    return engine


@bp.get("/backups")
@require_any("settings.manage", "audit.view")
@doc("وضعیت پشتیبان‌گیری و هشدارها")
def backup_status() -> ResponseReturnValue:
    s = new_session()
    try:
        return jsonify(_jsonable(backup.status(s) | {"history": backup.history(s)}))
    finally:
        s.close()


@bp.post("/backups/run")
@require("settings.manage")
@doc("پشتیبان‌گیری فوری")
def backup_now() -> ResponseReturnValue:
    actor = current_actor()
    try:
        result = backup.run_backup(_engine(), current_app.config["SETTINGS"])
    except Exception as e:
        current_app.logger.error("backup failed: %s", e)
        raise DomainError(
            "پشتیبان‌گیری ناموفق بود؛ جزئیات در تاریخچه پشتیبان‌گیری ثبت شد", code="backup_failed"
        ) from e
    with unit_of_work() as s:
        audit.record(s, "system.backup", user_id=actor.user_id, data={"path": result.path})
    return jsonify(
        {"path": result.path, "size_bytes": result.size_bytes, "verified": result.verified}
    ), 201


@bp.post("/backups/offsite-copied")
@require_any("settings.manage", "audit.view")
@doc("ثبت کپی نسخه پشتیبان به بیرون از سیستم")
def offsite_copied() -> ResponseReturnValue:
    actor = current_actor()
    with unit_of_work() as s:
        at = backup.mark_offsite(s)
        audit.record(s, "system.backup_copied_offsite", user_id=actor.user_id)
    return jsonify({"last_offsite_copy_at": at.isoformat()})


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    def conv(v: Any) -> Any:
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            return [conv(x) for x in v]
        return v

    return {k: conv(v) for k, v in d.items()}
