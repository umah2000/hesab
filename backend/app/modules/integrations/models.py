"""Documents received from other systems and posted here (ADR-0025)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Unicode,
    UnicodeText,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, EntityMixin, VersionedMixin

MONEY = Numeric(19, 4)


class IntegrationDocument(EntityMixin, VersionedMixin, Base):
    """One statement of the weighbridge platform: whether and by which voucher it is in
    the books. The voucher is never edited: a void is a reversal voucher."""

    __tablename__ = "integration_document"
    __table_args__ = (
        UniqueConstraint("source", "source_kind", "source_id"),
        CheckConstraint("status IN ('posted','held','voided','reversed')", name="status"),
        Index("ix_integration_document_status", "status", "created_at"),
    )

    source: Mapped[str] = mapped_column(String(16))  # "va"
    source_kind: Mapped[str] = mapped_column(String(24))  # "settlement"
    source_id: Mapped[str] = mapped_column(String(64))
    number: Mapped[str] = mapped_column(Unicode(32))
    kind: Mapped[str | None] = mapped_column(String(16))  # haulage | sales
    counterparty_code: Mapped[str | None] = mapped_column(Unicode(48))
    counterparty_name: Mapped[str | None] = mapped_column(Unicode(200))
    document_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(16))
    # Why it is held, in words the accountant can act on.
    problem: Mapped[str | None] = mapped_column(Unicode(500))
    # The approved statement as received (JSON), kept to post it again after a fix.
    payload: Mapped[str | None] = mapped_column(UnicodeText)
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    reversal_voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    void_reason: Mapped[str | None] = mapped_column(Unicode(500))


class IntegrationEvent(EntityMixin, Base):
    """Every event received, once (its id is the sender's): the log of the connection."""

    __tablename__ = "integration_event"
    __table_args__ = (
        UniqueConstraint("source", "event_id"),
        Index("ix_integration_event_received", "created_at"),
    )

    source: Mapped[str] = mapped_column(String(16))
    event_id: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("integration_document.id"))
    # posted | held | duplicate | voided | reversed | ignored
    result: Mapped[str] = mapped_column(String(16))
    message: Mapped[str | None] = mapped_column(Unicode(500))
