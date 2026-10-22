"""System endpoints: liveness and readiness (database reachability)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request
from flask.typing import ResponseReturnValue
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import new_session, unit_of_work
from app.core.errors import DomainError
from app.core.http import parse_body, to_json
from app.core.openapi import doc
from app.modules.audit import service as audit
from app.modules.iam.guard import current_actor, login_required, require, require_any
from app.modules.system import backup, license

bp = Blueprint("system", __name__)
VERSION_VIEW = ("settings.manage", "audit.view", "reports.dashboard")


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


@bp.get("/version")
@require_any(*VERSION_VIEW)
@doc("نسخه‌ی برنامه و دیتابیس")
def version() -> ResponseReturnValue:
    from app.modules.system.upgrade import revisions
    from app.version import RELEASED, VERSION

    current, head = revisions(_engine())
    return jsonify(
        {
            "version": VERSION,
            "released": RELEASED.isoformat(),
            "schema": current,
            "schema_head": head,
            "schema_ok": current == head,
        }
    )


# --- branding and about ---------------------------------------------------------


def _org_brand(s: Any) -> tuple[str, str | None]:
    from sqlalchemy import select

    from app.modules.organization.models import Organization

    row = s.execute(select(Organization.name, Organization.logo_sha256)).first()
    if row is None:
        return "", None
    return row[0], row[1][:16] if row[1] else None


@bp.get("/branding")
@doc("نام و نسخه‌ی لوگوی سازمان برای صفحه‌ی ورود (بدون ورود)")
def branding() -> ResponseReturnValue:
    s = new_session()
    try:
        name, logo_version = _org_brand(s)
    finally:
        s.close()
    return jsonify({"organization_name": name, "logo_version": logo_version})


@bp.get("/logo")
@doc("لوگوی سازمان (PNG؛ بدون ورود، برای صفحه‌ی ورود)")
def organization_logo() -> ResponseReturnValue:
    from app.modules.organization import services as org

    s = new_session()
    try:
        found = org.logo(s)
    finally:
        s.close()
    if found is None:
        return Response(status=404)
    data, sha = found
    resp = Response(data, mimetype="image/png")
    resp.set_etag(sha)
    # The URL carries ?v=<version>, so a new logo is a new URL; revalidate anyway.
    resp.headers["Cache-Control"] = "public, max-age=86400"
    resp.make_conditional(request)
    return resp


@bp.get("/about")
@login_required
@doc("درباره‌ی سازمان، نسخه‌ی برنامه و برنامه‌نویس")
def about() -> ResponseReturnValue:
    from app.modules.organization import services as org
    from app.vendor import DEVELOPER
    from app.version import RELEASED, VERSION

    s = new_session()
    try:
        o = org.get_organization(s)
    finally:
        s.close()
    return jsonify(
        {
            "organization": {
                "name": o.name,
                "about": o.about,
                "phone": o.phone,
                "address": o.address,
                "website": o.website,
                "logo_version": o.logo_version,
            },
            "app": {"name": "NEXTCAM ERP", "version": VERSION, "released": RELEASED.isoformat()},
            "developer": {k: v for k, v in DEVELOPER.items() if v},
        }
    )


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
        settings = current_app.config["SETTINGS"]
        return jsonify(
            _jsonable(
                backup.status(s)
                | {
                    "history": backup.history(s),
                    "encrypted_copies": bool(settings.backup_copy_dir),
                }
            )
        )
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
        {
            "path": result.path,
            "size_bytes": result.size_bytes,
            "verified": result.verified,
            "copy_path": result.copy.path if result.copy else None,
        }
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


# --- license (ADR-0021) ---------------------------------------------------------


@bp.get("/license")
@require_any("settings.manage", "reports.dashboard", "audit.view")
@doc("وضعیت مجوز نرم‌افزار، سقف‌ها و کد درخواست فعال‌سازی", response=license.LicenseStatus)
def license_status() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(license.status(s))
    finally:
        s.close()


@bp.post("/license")
@require("settings.manage")
@doc("نصب یا جایگزینی مجوز", body=license.LicenseIn, response=license.LicenseStatus)
def license_install() -> ResponseReturnValue:
    data = parse_body(license.LicenseIn)
    with unit_of_work() as s:
        return to_json(license.install(s, current_actor(), data.text))


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
