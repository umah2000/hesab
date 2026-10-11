from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from flask import Blueprint
from flask.typing import ResponseReturnValue
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.db import new_session
from app.core.http import MAX_PAGE_SIZE, Page, parse_query, to_json
from app.core.openapi import doc
from app.modules.audit.models import AuditEvent
from app.modules.iam.guard import current_actor, require
from app.modules.iam.models import AppUser

bp = Blueprint("audit", __name__)


class AuditQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)
    action: str | None = Field(default=None, max_length=64)
    user_id: uuid.UUID | None = None
    entity_id: str | None = Field(default=None, max_length=64)
    since: datetime | None = None
    until: datetime | None = None


class AuditEventOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    user_id: uuid.UUID | None
    username: str | None
    branch_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: str | None
    data: Any
    ip: str | None


@bp.get("/events")
@require("audit.view")
@doc("رویدادهای ممیزی (جدیدترین اول)", query=AuditQuery, response=AuditEventOut)
def list_events() -> ResponseReturnValue:
    q = parse_query(AuditQuery)
    actor = current_actor()
    stmt = select(AuditEvent, AppUser.username).outerjoin(AppUser, AppUser.id == AuditEvent.user_id)
    if q.action:
        stmt = stmt.where(AuditEvent.action.like(f"{q.action}%"))
    if q.user_id:
        stmt = stmt.where(AuditEvent.user_id == q.user_id)
    if q.entity_id:
        stmt = stmt.where(AuditEvent.entity_id == q.entity_id)
    if q.since:
        stmt = stmt.where(AuditEvent.occurred_at >= q.since)
    if q.until:
        stmt = stmt.where(AuditEvent.occurred_at < q.until)
    if actor.branch_ids is not None:
        # Branch-scoped auditors see their branches' events plus branchless ones they caused.
        stmt = stmt.where(
            AuditEvent.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)})
            | (AuditEvent.branch_id.is_(None) & (AuditEvent.user_id == actor.user_id))
        )
    s = new_session()
    try:
        total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = s.execute(
            stmt.order_by(AuditEvent.seq.desc())
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        ).all()
        items = [
            AuditEventOut(
                id=e.id,
                occurred_at=e.occurred_at,
                user_id=e.user_id,
                username=username,
                branch_id=e.branch_id,
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                data=json.loads(e.data) if e.data else None,
                ip=e.ip,
            )
            for e, username in rows
        ]
        return to_json(
            Page[AuditEventOut](items=items, total=total, page=q.page, page_size=q.page_size)
        )
    finally:
        s.close()
