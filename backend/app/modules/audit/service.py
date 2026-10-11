"""Audit trail. Events are written in the same transaction as the change they describe."""

from __future__ import annotations

import json
import uuid
from typing import Any

from flask import has_request_context, request
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent

# Never persisted in audit data, whatever the caller passes.
_REDACT = {"password", "password_hash", "token", "token_hash", "csrf", "csrf_hash", "pan", "pin"}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in _REDACT else _clean(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def record(
    session: Session,
    action: str,
    *,
    user_id: uuid.UUID | None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | str | None = None,
    branch_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            action=action,
            user_id=user_id,
            branch_id=branch_id,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            data=json.dumps(_clean(data), ensure_ascii=False, default=str) if data else None,
            ip=request.remote_addr if has_request_context() else None,
        )
    )
