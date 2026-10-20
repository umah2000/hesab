"""Counterparties (طرف‌حساب) — data-model.md §5, ADR-0014.

A party *is* a person detail account (shared primary key): vouchers, sales and the
credit limit keep pointing at ``detail_account``; this table adds identity, contact,
roles and notes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Unicode,
    func,
    text,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin


class PartyGroup(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "party_group"

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(Unicode(100))


class Party(ActorMixin, VersionedMixin, Base):
    __tablename__ = "party"
    __table_args__ = (
        CheckConstraint("party_type IN ('person','company')", name="party_type"),
        CheckConstraint("is_customer = 1 OR is_supplier = 1", name="has_role"),
        # National code / national ID is unique when given.
        Index(
            "uq_party_national_id",
            "national_id",
            unique=True,
            mssql_where=text("national_id IS NOT NULL"),
        ),
        Index("ix_party_group", "group_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detail_account.id"), primary_key=True)
    party_type: Mapped[str] = mapped_column(String(8), default="person")
    is_customer: Mapped[bool] = mapped_column(Boolean, default=True)
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("party_group.id"))
    # کد ملی (۱۰ رقم) for persons, شناسه ملی (۱۱ رقم) for companies.
    national_id: Mapped[str | None] = mapped_column(String(11))
    economic_code: Mapped[str | None] = mapped_column(String(16))
    registration_no: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(20))
    mobile: Mapped[str | None] = mapped_column(String(15))
    email: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(Unicode(60))
    address: Mapped[str | None] = mapped_column(Unicode(500))
    # Suppliers: default days until a purchase invoice is due.
    payment_terms_days: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.sysutcdatetime(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.sysutcdatetime(), nullable=False
    )


class PartyNote(EntityMixin, Base):
    """یادداشت و پیگیری: free text with an optional follow-up date."""

    __tablename__ = "party_note"
    __table_args__ = (Index("ix_party_note_party", "party_id", "created_at"),)

    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("party.id"))
    body: Mapped[str] = mapped_column(Unicode(1000))
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
