"""Backup history (phase 4, risk R2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, String, Unicode
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, EntityMixin


class BackupLog(EntityMixin, Base):
    __tablename__ = "backup_log"
    __table_args__ = (
        CheckConstraint("kind IN ('backup','restore_test')", name="kind"),
        CheckConstraint("status IN ('ok','failed')", name="status"),
        Index("ix_backup_log_kind_started", "kind", "started_at"),
    )

    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(8))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Path on the database server's disk; never a credential.
    file_path: Mapped[str | None] = mapped_column(Unicode(400))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(Unicode(1000))
