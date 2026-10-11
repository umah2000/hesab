"""Accounting data model (docs/database/data-model.md §2, ADR-0011)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Unicode,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin

MONEY = Numeric(19, 4)

ACCOUNT_LEVELS = ("group", "general", "subsidiary")
CATEGORIES = ("asset", "liability", "equity", "revenue", "expense")
NATURES = ("debit", "credit", "none")


class Account(EntityMixin, ActorMixin, VersionedMixin, Base):
    """Chart of accounts: گروه ← کل ← معین. Only subsidiary accounts take postings."""

    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint("level IN ('group','general','subsidiary')", name="level"),
        CheckConstraint(
            "category IN ('asset','liability','equity','revenue','expense')", name="category"
        ),
        CheckConstraint("nature IN ('debit','credit','none')", name="nature"),
        CheckConstraint(
            "(level = 'group' AND parent_id IS NULL) OR "
            "(level <> 'group' AND parent_id IS NOT NULL)",
            name="parent",
        ),
    )

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(Unicode(150))
    level: Mapped[str] = mapped_column(String(12))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("account.id"), index=True)
    category: Mapped[str] = mapped_column(String(12))
    nature: Mapped[str] = mapped_column(String(8))
    requires_detail: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Seeded accounts referenced by default posting rules cannot be deactivated while in use.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def is_postable(self) -> bool:
        return self.level == "subsidiary"


class DetailAccount(EntityMixin, ActorMixin, VersionedMixin, Base):
    """تفصیلی: person, bank, cash box, cost centre…"""

    __tablename__ = "detail_account"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('person','bank','cash','cost_center','project','other')", name="kind"
        ),
    )

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(Unicode(150))
    kind: Mapped[str] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class FiscalYear(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "fiscal_year"
    __table_args__ = (
        CheckConstraint("status IN ('open','closed')", name="status"),
        CheckConstraint("end_date > start_date", name="range"),
    )

    title: Mapped[str] = mapped_column(Unicode(100))
    jalali_year: Mapped[int] = mapped_column(Integer, unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    periods: Mapped[list[FiscalPeriod]] = relationship(
        back_populates="fiscal_year", order_by="FiscalPeriod.number", lazy="selectin"
    )


class FiscalPeriod(EntityMixin, VersionedMixin, Base):
    """Jalali month. A locked period accepts no new final vouchers."""

    __tablename__ = "fiscal_period"
    __table_args__ = (UniqueConstraint("fiscal_year_id", "number"),)

    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fiscal_year.id"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Unicode(50))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    fiscal_year: Mapped[FiscalYear] = relationship(back_populates="periods")


class Voucher(EntityMixin, ActorMixin, VersionedMixin, Base):
    """Accounting document. Draft = editable, unnumbered. Final = numbered, immutable.

    Database triggers (migration 0003) enforce: final vouchers and their lines
    cannot change or be deleted (except linking a reversal), and a voucher can
    only become final when balanced and non-empty.
    """

    __tablename__ = "voucher"
    __table_args__ = (
        CheckConstraint("status IN ('draft','final')", name="status"),
        CheckConstraint(
            "source_type IN ('manual','opening','closing','reversal','auto')", name="source_type"
        ),
        CheckConstraint("total_debit >= 0 AND total_credit >= 0", name="totals"),
        Index(
            "uq_voucher_number",
            "fiscal_year_id",
            "number",
            unique=True,
            mssql_where=text("number IS NOT NULL"),
        ),
        Index("ix_voucher_fy_status_date", "fiscal_year_id", "status", "document_date"),
        Index("ix_voucher_source", "source_type", "source_id"),
        # Triggers on these tables forbid SQL Server's OUTPUT clause.
        {"implicit_returning": False},
    )

    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branch.id"))
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fiscal_year.id"))
    number: Mapped[int | None] = mapped_column(Integer)
    document_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), default="draft")
    description: Mapped[str | None] = mapped_column(Unicode(500))
    source_type: Mapped[str] = mapped_column(String(12), default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[uuid.UUID | None] = mapped_column()
    total_debit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    total_credit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    reversed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[uuid.UUID | None] = mapped_column()

    lines: Mapped[list[VoucherLine]] = relationship(
        back_populates="voucher",
        order_by="VoucherLine.line_no",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class VoucherLine(EntityMixin, Base):
    __tablename__ = "voucher_line"
    __table_args__ = (
        CheckConstraint(
            "debit >= 0 AND credit >= 0 AND ((debit > 0 AND credit = 0) OR "
            "(credit > 0 AND debit = 0))",
            name="one_side",
        ),
        UniqueConstraint("voucher_id", "line_no"),
        Index("ix_voucher_line_account", "account_id", "voucher_id"),
        Index("ix_voucher_line_detail", "detail_account_id"),
        {"implicit_returning": False},
    )

    voucher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("voucher.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id"))
    detail_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("detail_account.id"))
    debit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    credit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    description: Mapped[str | None] = mapped_column(Unicode(300))

    voucher: Mapped[Voucher] = relationship(back_populates="lines")


class PostingRule(EntityMixin, ActorMixin, VersionedMixin, Base):
    """Which account each line role of an automatic voucher goes to (posting-rules.md)."""

    __tablename__ = "posting_rule"
    __table_args__ = (UniqueConstraint("event_type", "line_role"),)

    event_type: Mapped[str] = mapped_column(String(48))
    line_role: Mapped[str] = mapped_column(String(32))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("account.id"))
