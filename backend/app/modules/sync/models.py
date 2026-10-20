"""Operations pushed by register agents after working offline (ADR-0017, sync/protocol.md).

One row per operation id (the agent's Idempotency-Key): a resend returns the stored
result instead of applying twice. Conflicts wait here for a person; nothing is ever
resolved by last-write-wins.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Unicode,
    UnicodeText,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, EntityMixin, VersionedMixin

STATUSES = ("applied", "rejected", "conflict", "resolved", "discarded")


class SyncOperation(EntityMixin, VersionedMixin, Base):
    __tablename__ = "sync_operation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('applied','rejected','conflict','resolved','discarded')", name="status"
        ),
        CheckConstraint("op_type IN ('sale','line_removal')", name="op_type"),
        Index("ix_sync_operation_status", "status", "received_at"),
        Index("ix_sync_operation_device", "device_id", "received_at"),
    )

    # id = operation_id chosen by the agent.
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("device.id"))
    op_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(10))
    device_number: Mapped[str | None] = mapped_column(String(32))
    local_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[str] = mapped_column(UnicodeText)
    code: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str | None] = mapped_column(Unicode(500))
    # Sold total minus what the server's prices would have been at the time (+ = sold dearer).
    price_difference: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_invoice.id"))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Unicode(500))
