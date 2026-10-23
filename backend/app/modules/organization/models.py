from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
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
        CheckConstraint("invoice_paper IN ('thermal','a5','a4')", name="invoice_paper"),
    )

    name: Mapped[str] = mapped_column(Unicode(200))
    display_currency: Mapped[str] = mapped_column(String(3), default="IRT")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tehran")
    negative_stock_policy: Mapped[str] = mapped_column(String(8), default="warn")
    last_offsite_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sales settings (phase 4, ADR-0013).
    default_vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal(10))
    # Owner decision (1405/07/20): shelf prices exclude VAT; tax is added on the invoice.
    prices_include_vat: Mapped[bool] = mapped_column(Boolean, default=False)
    # Manual discount a cashier may give without a supervisor, as % of the invoice.
    # Owner decision: 0 — cashiers give no discount; only promotions apply.
    cashier_discount_limit: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal(0))
    backup_warning_days: Mapped[int] = mapped_column(Integer, default=3)
    receipt_header: Mapped[str | None] = mapped_column(Unicode(500))
    receipt_footer: Mapped[str | None] = mapped_column(Unicode(500))
    # Default paper for printing an invoice: the 80 mm roll, or A5 / A4 sheets.
    invoice_paper: Mapped[str] = mapped_column(String(8), default="thermal")
    # «درباره ما»: shown on the About page to every user.
    about: Mapped[str | None] = mapped_column(Unicode(2000))
    phone: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Unicode(300))
    website: Mapped[str | None] = mapped_column(String(200))
    # The logo as the server re-encoded it (PNG, ADR-0022); never read by a plain query.
    logo: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    logo_sha256: Mapped[str | None] = mapped_column(String(64))


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
