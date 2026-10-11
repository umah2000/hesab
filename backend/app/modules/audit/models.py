from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, PrimaryKeyConstraint, String, func
from sqlalchemy.dialects.mssql import NVARCHAR, UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditEvent(Base):
    """Append-only. UPDATE/DELETE are blocked by a database trigger (migration 0002)."""

    __tablename__ = "audit_event"
    __table_args__ = (
        PrimaryKeyConstraint("id", mssql_clustered=False),
        Index("ix_audit_event_seq", "seq", unique=True, mssql_clustered=True),
        Index("ix_audit_event_entity", "entity_type", "entity_id"),
        Index("ix_audit_event_user_time", "user_id", "occurred_at"),
        Index("ix_audit_event_action_time", "action", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity())
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.sysutcdatetime()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[str | None] = mapped_column(NVARCHAR(None))
    ip: Mapped[str | None] = mapped_column(String(45))
