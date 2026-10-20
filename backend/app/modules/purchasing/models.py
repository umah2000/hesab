"""Purchase orders, purchase invoices (with landed costs) and purchase returns — ADR-0014.

A purchase invoice is a draft until finalised; then goods enter stock at net cost plus
their share of landed costs, the voucher is posted from rules and the document is
immutable (DB triggers, migration 0008). A return points at the original invoice.
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin

MONEY = Numeric(19, 4)
QTY = Numeric(19, 3)
COST = Numeric(19, 6)
RATE = Numeric(5, 2)


class PurchaseOrder(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "purchase_order"
    __table_args__ = (
        CheckConstraint("status IN ('draft','approved','closed','cancelled')", name="status"),
        Index(
            "uq_purchase_order_number",
            "fiscal_year_id",
            "branch_id",
            "number",
            unique=True,
            mssql_where=text("number IS NOT NULL"),
        ),
        Index("ix_purchase_order_supplier", "supplier_id", "status"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse.id"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("party.id"))
    fiscal_year_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fiscal_year.id"))
    number: Mapped[int | None] = mapped_column(Integer)
    order_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="draft")
    note: Mapped[str | None] = mapped_column(Unicode(500))

    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="order",
        order_by="PurchaseOrderLine.line_no",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class PurchaseOrderLine(EntityMixin, Base):
    __tablename__ = "purchase_order_line"
    __table_args__ = (
        UniqueConstraint("order_id", "line_no"),
        CheckConstraint("qty > 0", name="qty"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_order.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"))
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    base_qty: Mapped[Decimal] = mapped_column(QTY)
    # Expected unit price, excluding VAT, per line unit.
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)

    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class PurchaseInvoice(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "purchase_invoice"
    __table_args__ = (
        CheckConstraint("kind IN ('invoice','return')", name="kind"),
        CheckConstraint("status IN ('draft','final')", name="status"),
        CheckConstraint(
            "(kind = 'return' AND original_invoice_id IS NOT NULL) OR "
            "(kind = 'invoice' AND original_invoice_id IS NULL)",
            name="return_original",
        ),
        CheckConstraint("status <> 'final' OR number IS NOT NULL", name="final_number"),
        Index(
            "uq_purchase_invoice_number",
            "fiscal_year_id",
            "branch_id",
            "kind",
            "number",
            unique=True,
            mssql_where=text("number IS NOT NULL"),
        ),
        Index("ix_purchase_invoice_supplier", "supplier_id", "document_date"),
        Index("ix_purchase_invoice_due", "status", "due_date"),
        {"implicit_returning": False},
    )

    kind: Mapped[str] = mapped_column(String(8), default="invoice")
    status: Mapped[str] = mapped_column(String(8), default="draft")
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse.id"))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("party.id"))
    fiscal_year_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fiscal_year.id"))
    number: Mapped[int | None] = mapped_column(Integer)
    # Receipt/registration date: drives stock and the voucher. The supplier's own
    # number and date are kept as printed on their invoice.
    document_date: Mapped[date] = mapped_column(Date)
    supplier_invoice_no: Mapped[str | None] = mapped_column(Unicode(40))
    supplier_invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_order.id"))
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_invoice.id"))
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    discount_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    tax_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    charges_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    # Owed to the supplier: net + VAT + landed costs the supplier billed.
    grand_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    # Value added to (or, for a return, removed from) stock.
    cost_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    note: Mapped[str | None] = mapped_column(Unicode(500))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    stock_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_document.id"))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list[PurchaseInvoiceLine]] = relationship(
        back_populates="invoice",
        order_by="PurchaseInvoiceLine.line_no",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    charges: Mapped[list[PurchaseCharge]] = relationship(
        back_populates="invoice",
        order_by="PurchaseCharge.line_no",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class PurchaseInvoiceLine(EntityMixin, Base):
    __tablename__ = "purchase_invoice_line"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no"),
        CheckConstraint("qty > 0", name="qty"),
        CheckConstraint("unit_cost >= 0 AND discount >= 0 AND tax >= 0", name="amounts"),
        Index("ix_purchase_invoice_line_item", "item_id"),
        Index("ix_purchase_invoice_line_original", "original_line_id"),
        Index("ix_purchase_invoice_line_order", "order_line_id"),
        {"implicit_returning": False},
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_invoice.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"))
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    base_qty: Mapped[Decimal] = mapped_column(QTY)
    # Supplier price per line unit, excluding VAT.
    unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    gross: Mapped[Decimal] = mapped_column(MONEY)
    discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    net: Mapped[Decimal] = mapped_column(MONEY)
    vat_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal(0))
    tax: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    # Share of the invoice's landed costs, by net value.
    landed: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    total_cost: Mapped[Decimal] = mapped_column(MONEY)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    order_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_order_line.id"))
    original_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchase_invoice_line.id")
    )

    invoice: Mapped[PurchaseInvoice] = relationship(back_populates="lines")


class PurchaseCharge(EntityMixin, Base):
    """هزینه جانبی: freight, unloading… spread over the goods' cost."""

    __tablename__ = "purchase_charge"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no"),
        CheckConstraint("amount > 0", name="amount"),
        {"implicit_returning": False},
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_invoice.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Unicode(200))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    # Who is owed: NULL = the invoice's supplier; otherwise e.g. the carrier.
    payee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("party.id"))

    invoice: Mapped[PurchaseInvoice] = relationship(back_populates="charges")
