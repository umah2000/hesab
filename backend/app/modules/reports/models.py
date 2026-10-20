"""Saved report filters (per user)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Unicode, UnicodeText, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, EntityMixin


class SavedReportFilter(EntityMixin, Base):
    __tablename__ = "saved_report_filter"
    __table_args__ = (UniqueConstraint("user_id", "report", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    report: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(Unicode(100))
    # The report's query parameters as JSON (validated again when the report runs).
    params: Mapped[str] = mapped_column(UnicodeText)
