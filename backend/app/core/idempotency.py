"""Idempotency-Key handling for create endpoints (ADR-0006).

Same key + same body  -> the stored response is replayed, nothing is created twice.
Same key + other body -> 409.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime

from flask import Response, request
from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func, select
from sqlalchemy.dialects.mssql import NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base
from app.core.errors import ConflictError, DomainError


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER)
    key: Mapped[str] = mapped_column(String(64))
    endpoint: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(NVARCHAR(None))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.sysutcdatetime(), index=True
    )


def _key() -> str:
    raw = (request.headers.get("Idempotency-Key") or "").strip()
    try:
        return str(uuid.UUID(raw))
    except ValueError as e:
        raise DomainError(
            "هدر Idempotency-Key (UUID) برای این عملیات الزامی است", code="idempotency_key_required"
        ) from e


def _request_hash() -> str:
    body = request.get_data(cache=True) or b""
    return hashlib.sha256(request.method.encode() + request.path.encode() + body).hexdigest()


def idempotent(
    session: Session, user_id: uuid.UUID, action: Callable[[], BaseModel], status: int = 201
) -> Response:
    """Run ``action`` once per Idempotency-Key, inside the caller's unit of work."""
    key = _key()
    req_hash = _request_hash()
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id, IdempotencyRecord.key == key
        )
    )
    if existing is not None:
        if existing.request_hash != req_hash:
            raise ConflictError(
                "این Idempotency-Key قبلاً با درخواست دیگری استفاده شده است",
                code="idempotency_key_reused",
            )
        return Response(
            existing.response_body,
            status=existing.status_code,
            mimetype="application/json",
            headers={"Idempotent-Replayed": "true"},
        )

    result = action()
    body = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    session.add(
        IdempotencyRecord(
            user_id=user_id,
            key=key,
            endpoint=f"{request.method} {request.path}"[:200],
            request_hash=req_hash,
            status_code=status,
            response_body=body,
        )
    )
    # A concurrent duplicate fails here on the unique constraint and rolls back.
    session.flush()
    return Response(body, status=status, mimetype="application/json")
