"""Weighbridge platform webhook and the accountant's view of what it sent (ADR-0025)."""

from __future__ import annotations

import time

from flask import Blueprint, current_app, jsonify, request
from flask.typing import ResponseReturnValue
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.db import new_session, unit_of_work
from app.core.http import parse_query, parse_uuid, to_json
from app.core.openapi import doc
from app.core.ratelimit import limiter
from app.modules.iam.guard import current_actor, require, require_any
from app.modules.integrations import service
from app.modules.integrations.schemas import (
    DocumentQuery,
    IntegrationDocumentOut,
    IntegrationStatusOut,
)

bp = Blueprint("integrations", __name__)
VIEW = ("accounting.integration.manage", "accounting.report.view")


def _settings() -> Settings:
    settings: Settings = current_app.config["SETTINGS"]
    return settings


@bp.post("/va/webhook")
@limiter.limit("600 per minute")
def va_webhook() -> ResponseReturnValue:
    """No session: the platform signs every request (HMAC, timestamp, organisation)."""
    body = request.get_data(cache=False)
    try:
        delivery = service.verify(_settings(), request.headers, body, time.time())
    except service.Rejected as e:
        return jsonify({"error": {"code": e.code}}), e.status
    for attempt in (0, 1):
        try:
            with unit_of_work() as s:
                reply = service.receive(s, _settings(), delivery)
            return jsonify(reply.body), reply.http_status
        except IntegrityError:
            # The same statement or event arrived twice at once: the second run sees the first.
            if attempt:
                raise
    raise AssertionError("unreachable")


@bp.get("/va/status")
@require_any(*VIEW)
@doc("وضعیت اتصال سامانه باسکول", response=IntegrationStatusOut)
def va_status() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(service.status(s, _settings()))
    finally:
        s.close()


@bp.get("/va/documents")
@require_any(*VIEW)
@doc("اسناد رسیده از سامانه باسکول", query=DocumentQuery, response=IntegrationDocumentOut)
def va_documents() -> ResponseReturnValue:
    q = parse_query(DocumentQuery)
    s = new_session()
    try:
        return to_json(service.list_documents(s, q))
    finally:
        s.close()


@bp.post("/va/documents/<doc_id>/retry")
@require("accounting.integration.manage")
@doc("ثبت دوباره پس از رفع مشکل", response=IntegrationDocumentOut)
def va_retry(doc_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(service.retry(s, _settings(), current_actor(), parse_uuid(doc_id)))
