"""Device Agents and their job queue — ADR-0015.

A Device Agent runs on a register PC and drives its local hardware (receipt printer,
cash drawer). It never receives commands from the browser: it connects *out* to this
server with its own device token and polls ``device_job``. The browser asks the server
to print; the server builds the receipt and queues a job for the register's agent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Unicode,
    UnicodeText,
    text,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin

TRANSPORTS = ("none", "tcp", "windows", "serial")
JOB_KINDS = ("receipt", "drawer", "test")
JOB_STATUSES = ("queued", "sent", "done", "failed", "expired")


class Device(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "device"
    __table_args__ = (
        CheckConstraint("status IN ('pending','active','revoked')", name="status"),
        CheckConstraint(
            "printer_transport IN ('none','tcp','windows','serial')", name="printer_transport"
        ),
        CheckConstraint("paper_width IN (58, 80)", name="paper_width"),
        CheckConstraint("drawer_pin IN (2, 5)", name="drawer_pin"),
        # One agent per register.
        Index(
            "uq_device_register",
            "cash_register_id",
            unique=True,
            mssql_where=text("cash_register_id IS NOT NULL AND status <> 'revoked'"),
        ),
        Index(
            "uq_device_token", "token_hash", unique=True, mssql_where=text("token_hash IS NOT NULL")
        ),
        Index(
            "uq_device_pairing",
            "pairing_code_hash",
            unique=True,
            mssql_where=text("pairing_code_hash IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(Unicode(100))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    cash_register_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cash_register.id"))
    status: Mapped[str] = mapped_column(String(8), default="pending")
    # Pairing: a short one-time code (hashed), typed into the agent on the register PC.
    pairing_code_hash: Mapped[str | None] = mapped_column(String(64))
    pairing_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The agent's bearer token (hashed); a new pairing replaces it.
    token_hash: Mapped[str | None] = mapped_column(String(64))
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agent_version: Mapped[str | None] = mapped_column(String(20))
    platform: Mapped[str | None] = mapped_column(Unicode(100))
    # Latest self-reported printer state ("ok" or a short error), never trusted for logic.
    printer_state: Mapped[str | None] = mapped_column(Unicode(200))
    # Receipt printer.
    printer_transport: Mapped[str] = mapped_column(String(8), default="none")
    # tcp: host:port · windows: printer name · serial: COM port (with baud, e.g. COM3:9600).
    printer_address: Mapped[str | None] = mapped_column(Unicode(120))
    paper_width: Mapped[int] = mapped_column(Integer, default=80)
    cut_paper: Mapped[bool] = mapped_column(Boolean, default=True)
    # Cash drawer on the printer's kick-out connector.
    drawer_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    drawer_pin: Mapped[int] = mapped_column(Integer, default=2)


class DeviceJob(EntityMixin, Base):
    __tablename__ = "device_job"
    __table_args__ = (
        CheckConstraint("kind IN ('receipt','drawer','test')", name="kind"),
        CheckConstraint("status IN ('queued','sent','done','failed','expired')", name="status"),
        Index("ix_device_job_next", "device_id", "status", "created_at"),
        Index("ix_device_job_source", "source_id"),
    )

    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("device.id"))
    kind: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(8), default="queued")
    # Rendering instructions (JSON). Only data, never code or raw printer bytes.
    payload: Mapped[str] = mapped_column(UnicodeText)
    # The sales invoice a receipt job prints (reprints share it).
    source_id: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Unicode(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
