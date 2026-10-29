"""What the visitor should hear about (ADR-0026).

Written in the same unit of work as the event (an order decided, a collection or a new
customer approved, a target set), read by the app on every sync. No push service: the
phone shows them when it fetches them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.distribution.models import VisitorNotification
from app.modules.distribution.schemas import NotificationOut, ReadIn
from app.modules.distribution.services import visitors
from app.modules.iam.guard import Actor

KEEP = 200  # the phone gets at most this many recent ones


def notify(
    s: Session,
    visitor_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
) -> None:
    s.add(
        VisitorNotification(
            visitor_id=visitor_id,
            kind=kind,
            title=title[:150],
            body=body[:300] if body else None,
            ref_type=ref_type,
            ref_id=ref_id,
        )
    )


def _out(n: VisitorNotification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        kind=n.kind,
        title=n.title,
        body=n.body,
        ref_type=n.ref_type,
        ref_id=n.ref_id,
        created_at=n.created_at,
        read_at=n.read_at,
    )


def mine(s: Session, actor: Actor, since: datetime | None) -> list[NotificationOut]:
    v = visitors.of_actor(s, actor)
    stmt = select(VisitorNotification).where(VisitorNotification.visitor_id == v.id)
    if since is not None:
        stmt = stmt.where(VisitorNotification.created_at > since)
    rows = list(s.scalars(stmt.order_by(VisitorNotification.created_at.desc()).limit(KEEP)))
    return [_out(n) for n in rows]


def mark_read(s: Session, actor: Actor, data: ReadIn) -> int:
    v = visitors.of_actor(s, actor)
    stmt = (
        update(VisitorNotification)
        .where(VisitorNotification.visitor_id == v.id, VisitorNotification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    if not data.all:
        if not data.ids:
            return 0
        stmt = stmt.where(VisitorNotification.id.in_(data.ids))
    result = s.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)
