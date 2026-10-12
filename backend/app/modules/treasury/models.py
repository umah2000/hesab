"""Treasury (خزانه‌داری): cash boxes and bank accounts, receipts, payments, transfers,
card-reader settlements, cheques with their history, and bank statements — ADR-0014.

Every money account *is* a ``cash``/``bank`` detail account (shared primary key), so
its balance is the sum of final voucher lines carrying it. Treasury documents are final
on creation (their voucher is posted in the same unit of work) and can only be
reversed, never edited (DB triggers, migration 0009).
"""

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
    Integer,
    Numeric,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin

MONEY = Numeric(19, 4)


class MoneyAccount(ActorMixin, VersionedMixin, Base):
    __tablename__ = "money_account"
    __table_args__ = (CheckConstraint("kind IN ('cash','bank')", name="kind"),)

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detail_account.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(4))
    # Cash boxes belong to a branch; a bank account may serve every branch (NULL).
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branch.id"))
    bank_name: Mapped[str | None] = mapped_column(Unicode(100))
    bank_branch: Mapped[str | None] = mapped_column(Unicode(100))
    account_no: Mapped[str | None] = mapped_column(String(30))
    # شبا: IR + 24 digits.
    iban: Mapped[str | None] = mapped_column(String(26))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.sysutcdatetime(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.sysutcdatetime(),
        onupdate=func.sysutcdatetime(),
        nullable=False,
    )


class TreasuryDocument(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "treasury_document"
    __table_args__ = (
        CheckConstraint("kind IN ('receipt','payment','transfer','settlement')", name="kind"),
        CheckConstraint("status IN ('draft','final','reversed')", name="status"),
        CheckConstraint("against IS NULL OR against IN ('receivable','payable')", name="against"),
        CheckConstraint("amount > 0 AND fee >= 0", name="amounts"),
        CheckConstraint("status = 'draft' OR number IS NOT NULL", name="final_number"),
        Index(
            "uq_treasury_document_number",
            "fiscal_year_id",
            "branch_id",
            "kind",
            "number",
            unique=True,
            mssql_where=text("number IS NOT NULL"),
        ),
        Index("ix_treasury_document_party", "party_id", "document_date"),
        Index("ix_treasury_document_date", "document_date"),
        {"implicit_returning": False},
    )

    kind: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(8), default="draft")
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fiscal_year.id"))
    number: Mapped[int | None] = mapped_column(Integer)
    document_date: Mapped[date] = mapped_column(Date)
    # Receipts and payments: the counterparty and which side of its account moves.
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("party.id"))
    against: Mapped[str | None] = mapped_column(String(10))
    # Transfers: from → to. Settlements: the bank account credited.
    from_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("money_account.id"))
    to_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("money_account.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    # Settlements: the bank's fee withheld from the card-reader total.
    fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    reference: Mapped[str | None] = mapped_column(Unicode(60))
    description: Mapped[str | None] = mapped_column(Unicode(500))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    reversal_voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    reversal_reason: Mapped[str | None] = mapped_column(Unicode(500))

    lines: Mapped[list[TreasuryLine]] = relationship(
        back_populates="document",
        order_by="TreasuryLine.line_no",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class TreasuryLine(EntityMixin, Base):
    """One instrument of a receipt or payment: cash, bank transfer/POS slip, or cheque."""

    __tablename__ = "treasury_line"
    __table_args__ = (
        UniqueConstraint("document_id", "line_no"),
        CheckConstraint("method IN ('cash','bank','cheque')", name="method"),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint(
            "(method = 'cheque' AND cheque_id IS NOT NULL) OR "
            "(method <> 'cheque' AND cheque_id IS NULL AND money_account_id IS NOT NULL)",
            name="instrument",
        ),
        Index("ix_treasury_line_account", "money_account_id"),
        {"implicit_returning": False},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("treasury_document.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(6))
    money_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("money_account.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    reference: Mapped[str | None] = mapped_column(Unicode(60))
    cheque_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cheque.id"))

    document: Mapped[TreasuryDocument] = relationship(back_populates="lines")


RECEIVED_STATUSES = ("in_hand", "deposited", "cleared", "bounced", "returned", "void")
ISSUED_STATUSES = ("issued", "cleared", "bounced", "cancelled", "void")


class Cheque(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "cheque"
    __table_args__ = (
        CheckConstraint("direction IN ('received','issued')", name="direction"),
        CheckConstraint(
            "status IN ('in_hand','deposited','cleared','bounced','returned','issued',"
            "'cancelled','void')",
            name="status",
        ),
        CheckConstraint("amount > 0", name="amount"),
        Index("ix_cheque_due", "direction", "status", "due_date"),
        Index("ix_cheque_party", "party_id"),
        # One Sayad ID per direction (the same cheque can come in, then go out endorsed —
        # not supported yet, so it is simply unique per direction).
        Index(
            "uq_cheque_sayad",
            "direction",
            "sayad_id",
            unique=True,
            mssql_where=text("sayad_id IS NOT NULL AND status <> 'void'"),
        ),
        {"implicit_returning": False},
    )

    direction: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10))
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("party.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    number: Mapped[str] = mapped_column(String(30))
    # شناسه صیادی: 16 digits.
    sayad_id: Mapped[str | None] = mapped_column(String(16))
    bank_name: Mapped[str | None] = mapped_column(Unicode(100))
    drawer: Mapped[str | None] = mapped_column(Unicode(150))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    due_date: Mapped[date] = mapped_column(Date)
    # Issued: the account it is drawn on. Received: where it was deposited.
    money_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("money_account.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("treasury_document.id"))

    events: Mapped[list[ChequeEvent]] = relationship(
        back_populates="cheque", order_by="ChequeEvent.seq", lazy="selectin"
    )


class ChequeEvent(EntityMixin, Base):
    """Append-only history of a cheque's status (DB trigger, migration 0009)."""

    __tablename__ = "cheque_event"
    __table_args__ = (UniqueConstraint("cheque_id", "seq"), {"implicit_returning": False})

    cheque_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cheque.id"))
    seq: Mapped[int] = mapped_column(Integer)
    event_date: Mapped[date] = mapped_column(Date)
    from_status: Mapped[str | None] = mapped_column(String(10))
    to_status: Mapped[str] = mapped_column(String(10))
    money_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("money_account.id"))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    note: Mapped[str | None] = mapped_column(Unicode(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))

    cheque: Mapped[Cheque] = relationship(back_populates="events")


class BankStatementLine(EntityMixin, ActorMixin, Base):
    """A line of an imported bank statement, matched to at most one voucher line."""

    __tablename__ = "bank_statement_line"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="amount"),
        # Re-importing an overlapping statement skips lines already present.
        UniqueConstraint("money_account_id", "fingerprint"),
        Index(
            "uq_bank_statement_line_voucher_line",
            "voucher_line_id",
            unique=True,
            mssql_where=text("voucher_line_id IS NOT NULL"),
        ),
        Index("ix_bank_statement_line_date", "money_account_id", "line_date", "seq"),
    )

    money_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("money_account.id"))
    # Order of the lines as the bank printed them (same-day lines keep their order).
    seq: Mapped[int] = mapped_column(Integer)
    line_date: Mapped[date] = mapped_column(Date)
    # Positive = deposit into the account, negative = withdrawal.
    amount: Mapped[Decimal] = mapped_column(MONEY)
    description: Mapped[str | None] = mapped_column(Unicode(300))
    reference: Mapped[str | None] = mapped_column(Unicode(60))
    # Running balance as printed by the bank, when given.
    balance: Mapped[Decimal | None] = mapped_column(MONEY)
    fingerprint: Mapped[str] = mapped_column(String(64))
    voucher_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher_line.id"))
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
