"""Centralised error handling. Public responses never leak internal details."""

from __future__ import annotations

import uuid

import structlog
from flask import Flask, jsonify
from flask.typing import ResponseReturnValue
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException

log = structlog.get_logger(__name__)


class DomainError(Exception):
    """A business-rule violation that is safe to show to the user."""

    status_code = 422
    code = "domain_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "permission_denied"


def _error(status: int, code: str, message: str, **extra: object) -> ResponseReturnValue:
    return jsonify({"error": {"code": code, "message": message, **extra}}), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(DomainError)
    def _domain(e: DomainError) -> ResponseReturnValue:
        return _error(e.status_code, e.code, e.message)

    @app.errorhandler(ValidationError)
    def _validation(e: ValidationError) -> ResponseReturnValue:
        details = [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()]
        return _error(400, "validation_error", "ورودی نامعتبر است", details=details)

    @app.errorhandler(StaleDataError)
    def _stale(e: StaleDataError) -> ResponseReturnValue:
        return _error(409, "version_conflict", "این رکورد هم‌زمان تغییر کرده است؛ صفحه را تازه کنید")

    @app.errorhandler(IntegrityError)
    def _integrity(e: IntegrityError) -> ResponseReturnValue:
        incident = uuid.uuid4().hex[:12]
        log.warning("integrity_error", incident=incident, error=str(e.orig)[:500])
        return _error(409, "conflict", "اطلاعات تکراری یا ناسازگار است", incident=incident)

    @app.errorhandler(HTTPException)
    def _http(e: HTTPException) -> ResponseReturnValue:
        messages = {
            404: "مسیر یافت نشد",
            405: "این روش برای مسیر مجاز نیست",
            413: "حجم درخواست بیش از حد مجاز است",
            429: "تعداد درخواست‌ها بیش از حد مجاز است؛ کمی صبر کنید",
        }
        code = e.code or 500
        return _error(
            code,
            (e.name or "http_error").lower().replace(" ", "_"),
            messages.get(code, e.description or ""),
        )

    @app.errorhandler(Exception)
    def _unhandled(e: Exception) -> ResponseReturnValue:
        incident = uuid.uuid4().hex[:12]
        log.exception("unhandled_error", incident=incident)
        return _error(500, "internal_error", "خطای داخلی سامانه", incident=incident)
