from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Unicode,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin


class Organization(EntityMixin, ActorMixin, VersionedMixin, Base):
    """Exactly one row per installation (ADR-0003)."""

    __tablename__ = "organization"
    __table_args__ = (
        CheckConstraint("display_currency IN ('IRR','IRT')", name="display_currency"),
        CheckConstraint(
            "negative_stock_policy IN ('deny','warn','allow')", name="negative_stock_policy"
        ),
    )

    name: Mapped[str] = mapped_column(Unicode(200))
    display_currency: Mapped[str] = mapped_column(String(3), default="IRT")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tehran")
    negative_stock_policy: Mapped[str] = mapped_column(String(8), default="warn")
    last_offsite_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Branch(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "branch"

    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(Unicode(150))
    address: Mapped[str | None] = mapped_column(Unicode(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CashRegister(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "cash_register"
    __table_args__ = (UniqueConstraint("branch_id", "code"),)

    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), index=True)
    code: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(Unicode(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
