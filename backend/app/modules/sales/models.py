"""Shifts, sales invoices, payments, promotions, approvals and card transactions.

data-model.md §4, ADR-0013. A final invoice and its lines are immutable (DB triggers,
migration 0005); corrections are made with a return invoice.
"""

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
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin

MONEY = Numeric(19, 4)
QTY = Numeric(19, 3)
RATE = Numeric(5, 2)


class CashShift(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "cash_shift"
    __table_args__ = (
        CheckConstraint("status IN ('open','closed')", name="status"),
        # One open shift per register and one per cashier.
        Index(
            "uq_cash_shift_open_register",
            "cash_register_id",
            unique=True,
            mssql_where=text("status = 'open'"),
        ),
        Index(
            "uq_cash_shift_open_user", "user_id", unique=True, mssql_where=text("status = 'open'")
        ),
        Index("ix_cash_shift_register_opened", "cash_register_id", "opened_at"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    cash_register_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cash_register.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    status: Mapped[str] = mapped_column(String(8), default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opening_cash: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
    expected_cash: Mapped[Decimal | None] = mapped_column(MONEY)
    counted_cash: Mapped[Decimal | None] = mapped_column(MONEY)
    # counted − expected: negative = shortage, positive = overage.
    difference: Mapped[Decimal | None] = mapped_column(MONEY)
    close_note: Mapped[str | None] = mapped_column(Unicode(500))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))


class SalesInvoice(EntityMixin, ActorMixin, VersionedMixin, Base):
    """kind = sale | return.

    status: held (suspended cart) → recalled; or draft → final within one transaction
    (lines are written while draft, as with vouchers, so the DB guard can be strict).
    """

    __tablename__ = "sales_invoice"
    __table_args__ = (
        CheckConstraint("kind IN ('sale','return')", name="kind"),
        CheckConstraint("status IN ('draft','held','recalled','final')", name="status"),
        CheckConstraint(
            "(kind = 'return' AND original_invoice_id IS NOT NULL) OR "
            "(kind = 'sale' AND original_invoice_id IS NULL)",
            name="return_original",
        ),
        CheckConstraint("status <> 'final' OR number IS NOT NULL", name="final_number"),
        Index(
            "uq_sales_invoice_number",
            "fiscal_year_id",
            "branch_id",
            "kind",
            "number",
            unique=True,
            mssql_where=text("number IS NOT NULL"),
        ),
        Index("ix_sales_invoice_branch_date", "branch_id", "document_date", "status"),
        Index("ix_sales_invoice_shift", "shift_id"),
        Index("ix_sales_invoice_original", "original_invoice_id"),
        # A number typed by the user (company standard), besides the automatic one (ADR-0029).
        Index(
            "uq_sales_invoice_manual_number",
            "kind",
            "manual_number",
            unique=True,
            mssql_where=text("manual_number IS NOT NULL"),
        ),
        # Offline sales: the number printed on the receipt at the register (ADR-0005).
        Index(
            "uq_sales_invoice_device_number",
            "device_number",
            unique=True,
            mssql_where=text("device_number IS NOT NULL"),
        ),
        {"implicit_returning": False},
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    cash_register_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cash_register.id"))
    shift_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cash_shift.id"))
    fiscal_year_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fiscal_year.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse.id"))
    kind: Mapped[str] = mapped_column(String(8), default="sale")
    status: Mapped[str] = mapped_column(String(10))
    number: Mapped[int | None] = mapped_column(Integer)
    # Optional number given by the user; the automatic, gap-free ``number`` stays (ADR-0029).
    manual_number: Mapped[str | None] = mapped_column(String(30))
    document_date: Mapped[date] = mapped_column(Date)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("detail_account.id"))
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_invoice.id"))
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    discount_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    tax_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    grand_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    cost_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    cash_tendered: Mapped[Decimal | None] = mapped_column(MONEY)
    change_due: Mapped[Decimal | None] = mapped_column(MONEY)
    note: Mapped[str | None] = mapped_column(Unicode(300))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    stock_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_document.id"))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Reserved for the Moadian tax system (version 2, ADR-0009).
    # Offline sale (ADR-0017): receipt number from the register and when it really happened.
    device_number: Mapped[str | None] = mapped_column(String(32))
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tax_invoice_number: Mapped[str | None] = mapped_column(String(32))
    tax_submission_status: Mapped[str | None] = mapped_column(String(16))

    lines: Mapped[list[SalesInvoiceLine]] = relationship(
        back_populates="invoice",
        order_by="SalesInvoiceLine.line_no",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list[SalesPayment]] = relationship(
        back_populates="invoice",
        order_by="SalesPayment.seq",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class SalesInvoiceLine(EntityMixin, Base):
    __tablename__ = "sales_invoice_line"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no"),
        CheckConstraint("qty > 0", name="qty"),
        Index("ix_sales_invoice_line_item", "item_id"),
        Index("ix_sales_invoice_line_original", "original_line_id"),
        {"implicit_returning": False},
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_invoice.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"))
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    base_qty: Mapped[Decimal] = mapped_column(QTY)
    # Price per line unit as charged (VAT-inclusive when the organisation prices so).
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    # list | scale (price read from a scale price label)
    price_source: Mapped[str] = mapped_column(String(8), default="list")
    gross: Mapped[Decimal] = mapped_column(MONEY)
    promotion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("promotion.id"))
    promotion_discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    manual_discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    vat_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal(0))
    tax: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    # Net of discounts and tax.
    revenue: Mapped[Decimal] = mapped_column(MONEY)
    # What the customer pays for the line.
    line_total: Mapped[Decimal] = mapped_column(MONEY)
    cost_total: Mapped[Decimal | None] = mapped_column(MONEY)
    scanned_barcode: Mapped[str | None] = mapped_column(String(48))
    original_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_invoice_line.id"))

    invoice: Mapped[SalesInvoice] = relationship(back_populates="lines")


class SalesPayment(EntityMixin, Base):
    """A sale may be paid by several methods; on a return these are refunds."""

    __tablename__ = "sales_payment"
    __table_args__ = (
        CheckConstraint("method IN ('cash','card','credit')", name="method"),
        CheckConstraint("amount > 0", name="amount"),
        CheckConstraint(
            "method <> 'card' OR card_reference IS NOT NULL OR terminal_transaction_id IS NOT NULL",
            name="card_evidence",
        ),
        Index("ix_sales_payment_invoice", "invoice_id"),
        # A card transaction pays at most one invoice (NULLs allowed many times).
        Index(
            "uq_sales_payment_terminal_tx",
            "terminal_transaction_id",
            unique=True,
            mssql_where=text("terminal_transaction_id IS NOT NULL"),
        ),
        {"implicit_returning": False},
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_invoice.id"))
    seq: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    # Pilot path: tracking number typed from a standalone card reader's slip.
    card_reference: Mapped[str | None] = mapped_column(String(32))
    terminal_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("terminal_transaction.id")
    )

    invoice: Mapped[SalesInvoice] = relationship(back_populates="payments")


class Promotion(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "promotion"
    __table_args__ = (
        CheckConstraint("kind IN ('percent','amount')", name="kind"),
        CheckConstraint("scope IN ('item','group')", name="scope"),
        CheckConstraint(
            "(scope = 'item' AND item_id IS NOT NULL AND group_id IS NULL) OR "
            "(scope = 'group' AND group_id IS NOT NULL AND item_id IS NULL)",
            name="target",
        ),
        CheckConstraint("value > 0 AND (kind <> 'percent' OR value <= 100)", name="value"),
        CheckConstraint("ends_on >= starts_on", name="dates"),
        Index("ix_promotion_active_dates", "is_active", "starts_on", "ends_on"),
    )

    name: Mapped[str] = mapped_column(Unicode(150))
    kind: Mapped[str] = mapped_column(String(8))
    scope: Mapped[str] = mapped_column(String(8))
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item.id"))
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_group.id"))
    # percent: 0–100; amount: rials off per base unit.
    value: Mapped[Decimal] = mapped_column(MONEY)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SalesApproval(EntityMixin, Base):
    """A supervisor's password-confirmed approval of one sensitive action on a register."""

    __tablename__ = "sales_approval"
    __table_args__ = (
        CheckConstraint(
            "action IN ('line_delete','discount_over_limit','return')",
            name="action",
        ),
    )

    action: Mapped[str] = mapped_column(String(24))
    cash_register_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cash_register.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CardTerminal(EntityMixin, ActorMixin, VersionedMixin, Base):
    """A bank card reader the program can send amounts to (ADR-0023).

    The provider names the driver that speaks its protocol; a provider without a
    driver can be defined (so the shop's devices are on record) but is not sent to.
    """

    __tablename__ = "card_terminal"
    __table_args__ = (
        CheckConstraint("provider IN ('sep','sep_central','mock')", name="provider"),
        CheckConstraint("port IS NULL OR (port BETWEEN 1 AND 65535)", name="port"),
    )

    name: Mapped[str] = mapped_column(Unicode(100), unique=True)
    provider: Mapped[str] = mapped_column(String(16))
    host: Mapped[str | None] = mapped_column(String(64))
    port: Mapped[int | None] = mapped_column(Integer)
    # The terminal number on the PSP's slip, when the protocol needs it.
    terminal_no: Mapped[str | None] = mapped_column(String(16))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    # The register that uses it by default (several registers may share one reader).
    cash_register_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cash_register.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Unicode(300))


class TerminalTransaction(EntityMixin, VersionedMixin, Base):
    """One card-reader request (hardware/payment-terminal-adapter.md). Never PAN/PIN."""

    __tablename__ = "terminal_transaction"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Created','Pending','Approved','Declined','Unknown',"
            "'ReconciliationRequired','Cancelled')",
            name="status",
        ),
        CheckConstraint("amount > 0", name="amount"),
        Index("ix_terminal_transaction_register_status", "cash_register_id", "status"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, unique=True)
    cash_register_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cash_register.id"))
    # Client-side cart id; ties the attempt to one sale before the invoice exists.
    cart_id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, index=True)
    adapter_id: Mapped[str] = mapped_column(String(32))
    # The reader it was sent to (NULL: the built-in development mock).
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("card_terminal.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(24))
    rrn: Mapped[str | None] = mapped_column(String(32))
    trace_no: Mapped[str | None] = mapped_column(String(32))
    masked_pan: Mapped[str | None] = mapped_column(String(19))
    response_code: Mapped[str | None] = mapped_column(String(16))
    # The provider's own id for this attempt (SEP central: Identifier), saved before the
    # amount is sent so the attempt can always be inquired.
    provider_ref: Mapped[str | None] = mapped_column(String(64))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
    resolution_note: Mapped[str | None] = mapped_column(Unicode(300))
