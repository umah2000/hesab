"""Items, barcodes, prices, warehouses and the stock ledger (data-model.md §3, ADR-0012)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Unicode,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin

MONEY = Numeric(19, 4)
QTY = Numeric(19, 3)
COST = Numeric(19, 6)
FACTOR = Numeric(19, 6)


class Unit(EntityMixin, VersionedMixin, Base):
    __tablename__ = "unit"

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(Unicode(50))
    allows_fraction: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemGroup(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "item_group"

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(Unicode(100))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_group.id"))


class Item(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "item"
    __table_args__ = (
        CheckConstraint("item_type IN ('goods','service')", name="item_type"),
        CheckConstraint("vat_rate IS NULL OR (vat_rate >= 0 AND vat_rate <= 100)", name="vat_rate"),
        # PLU printed by the label scale; unique when present.
        Index(
            "uq_item_scale_code",
            "scale_code",
            unique=True,
            mssql_where=text("scale_code IS NOT NULL"),
        ),
        Index("ix_item_group", "group_id"),
        Index("ix_item_name", "name"),
    )

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(Unicode(200))
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_group.id"))
    base_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit.id"))
    item_type: Mapped[str] = mapped_column(String(8), default="goods")
    is_weighted: Mapped[bool] = mapped_column(Boolean, default=False)
    scale_code: Mapped[str | None] = mapped_column(String(8))
    track_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    # VAT: exempt is not the same as a zero rate (ADR-0009, Q6).
    vat_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    tax_item_code: Mapped[str | None] = mapped_column(String(32))
    min_qty: Mapped[Decimal | None] = mapped_column(QTY)
    max_qty: Mapped[Decimal | None] = mapped_column(QTY)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    barcodes: Mapped[list[ItemBarcode]] = relationship(
        back_populates="item", lazy="selectin", cascade="all, delete-orphan"
    )
    units: Mapped[list[ItemUnit]] = relationship(
        back_populates="item", lazy="selectin", cascade="all, delete-orphan"
    )


class ItemUnit(EntityMixin, Base):
    """Alternative unit: 1 <unit> = factor × base unit (e.g. 1 carton = 24 pieces)."""

    __tablename__ = "item_unit"
    __table_args__ = (
        UniqueConstraint("item_id", "unit_id"),
        CheckConstraint("factor > 0", name="factor"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"))
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit.id"))
    factor: Mapped[Decimal] = mapped_column(FACTOR)

    item: Mapped[Item] = relationship(back_populates="units")


class ItemBarcode(EntityMixin, Base):
    """Every barcode of an item. A pack barcode points at an alternative unit."""

    __tablename__ = "item_barcode"

    barcode: Mapped[str] = mapped_column(String(48), unique=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"), index=True)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("unit.id"))

    item: Mapped[Item] = relationship(back_populates="barcodes")


class ItemImage(EntityMixin, ActorMixin, Base):
    """A product photo, re-encoded by the server (ADR-0022). Never edited: a new upload is a
    new id, so clients cache an image by id forever. The bytes are deferred: lists never
    read them."""

    __tablename__ = "item_image"
    __table_args__ = (
        UniqueConstraint("item_id", "sha256"),
        CheckConstraint("position >= 0", name="position"),
    )

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"), index=True)
    # 0 = the main image.
    position: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Of the large JPEG; the ETag.
    sha256: Mapped[str] = mapped_column(String(64))
    large: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    thumb: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class ScaleBarcodeRule(EntityMixin, ActorMixin, VersionedMixin, Base):
    """A label scale's barcode: [prefix][PLU][value] (12 digits), then an EAN-13 check
    digit, or none on scales that print a plain 12-digit code (``check_digit`` off)."""

    __tablename__ = "scale_barcode_rule"
    __table_args__ = (
        CheckConstraint("value_type IN ('weight','price')", name="value_type"),
        CheckConstraint("LEN(prefix) + item_code_length + value_length = 12", name="length"),
    )

    name: Mapped[str] = mapped_column(Unicode(100))
    prefix: Mapped[str] = mapped_column(String(4), unique=True)
    item_code_length: Mapped[int] = mapped_column(Integer)
    value_length: Mapped[int] = mapped_column(Integer)
    value_type: Mapped[str] = mapped_column(String(8))
    # weight: digits / 10^decimals = kg (3 → grams). price: digits = rials × 10^decimals.
    value_decimals: Mapped[int] = mapped_column(Integer, default=3)
    check_digit: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PriceList(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "price_list"

    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(Unicode(100))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ItemPrice(EntityMixin, ActorMixin, Base):
    """Price per unit in rials. History lives in the audit trail."""

    __tablename__ = "item_price"
    __table_args__ = (
        UniqueConstraint("price_list_id", "item_id", "unit_id"),
        CheckConstraint("price >= 0", name="price"),
    )

    price_list_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_list.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"), index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit.id"))
    price: Mapped[Decimal] = mapped_column(MONEY)


class Warehouse(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "warehouse"

    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"), index=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(Unicode(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


STOCK_DOC_TYPES = ("opening", "adjustment", "transfer", "count")
# Created by other modules (sales, later purchasing), never by hand.
SYSTEM_DOC_TYPES = ("sale", "sale_return", "purchase", "purchase_return")


class StockDocument(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "stock_document"
    __table_args__ = (
        CheckConstraint(
            "doc_type IN ('opening','adjustment','transfer','count','sale','sale_return',"
            "'purchase','purchase_return')",
            name="doc_type",
        ),
        CheckConstraint("status IN ('draft','final')", name="status"),
        CheckConstraint(
            "(doc_type = 'transfer' AND dest_warehouse_id IS NOT NULL "
            "AND dest_warehouse_id <> warehouse_id) OR "
            "(doc_type <> 'transfer' AND dest_warehouse_id IS NULL)",
            name="transfer_dest",
        ),
        Index(
            "uq_stock_document_number",
            "fiscal_year_id",
            "branch_id",
            "number",
            unique=True,
            mssql_where=text("number IS NOT NULL"),
        ),
        Index("ix_stock_document_wh_date", "warehouse_id", "document_date"),
        Index("ix_stock_document_source", "source_type", "source_id"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse.id"))
    dest_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouse.id"))
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fiscal_year.id"))
    doc_type: Mapped[str] = mapped_column(String(16))
    number: Mapped[int | None] = mapped_column(Integer)
    document_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), default="draft")
    description: Mapped[str | None] = mapped_column(Unicode(500))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voucher.id"))
    # A finalised count produces an adjustment that points back at it.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_document.id"))
    # Owning document of another module, e.g. ("sales_invoice", id). No FK across modules.
    source_type: Mapped[str | None] = mapped_column(String(16))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list[StockDocumentLine]] = relationship(
        back_populates="document",
        order_by="StockDocumentLine.line_no",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class StockDocumentLine(EntityMixin, Base):
    __tablename__ = "stock_document_line"
    __table_args__ = (UniqueConstraint("document_id", "line_no"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_document.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"), index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit.id"))
    # In the line's unit. Signed for adjustments (+ surplus / − shortage);
    # for counts this is the counted quantity.
    qty: Mapped[Decimal] = mapped_column(QTY)
    base_qty: Mapped[Decimal] = mapped_column(QTY)
    # Per line unit, rials. Required for opening stock and for surplus of an item with no cost yet.
    unit_cost: Mapped[Decimal | None] = mapped_column(COST)
    total_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    system_qty: Mapped[Decimal | None] = mapped_column(QTY)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Unicode(300))

    document: Mapped[StockDocument] = relationship(back_populates="lines")


class StockLedger(Base):
    """کاردکس. Append-only (trigger, migration 0004). One row per movement per warehouse."""

    __tablename__ = "stock_ledger"
    __table_args__ = (
        PrimaryKeyConstraint("id", mssql_clustered=False),
        Index(
            "ix_stock_ledger_item_wh_seq",
            "item_id",
            "warehouse_id",
            "seq",
            unique=True,
            mssql_clustered=True,
        ),
        Index("ix_stock_ledger_document", "document_id"),
        {"implicit_returning": False},
    )

    id: Mapped[uuid.UUID] = mapped_column(UNIQUEIDENTIFIER, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(BigInteger, Identity())
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse.id"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_document.id"))
    document_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_document_line.id"))
    document_date: Mapped[date] = mapped_column(Date)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.sysutcdatetime()
    )
    qty_in: Mapped[Decimal] = mapped_column(QTY, default=Decimal(0))
    qty_out: Mapped[Decimal] = mapped_column(QTY, default=Decimal(0))
    value_in: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    value_out: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    balance_qty: Mapped[Decimal] = mapped_column(QTY)
    balance_value: Mapped[Decimal] = mapped_column(MONEY)
    avg_cost: Mapped[Decimal] = mapped_column(COST)


class StockBalance(VersionedMixin, Base):
    """Current quantity/value per item and warehouse; updated only with the ledger."""

    __tablename__ = "stock_balance"
    __table_args__ = (PrimaryKeyConstraint("item_id", "warehouse_id"),)

    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse.id"))
    qty: Mapped[Decimal] = mapped_column(QTY, default=Decimal(0))
    value: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    avg_cost: Mapped[Decimal] = mapped_column(COST, default=Decimal(0))
    last_movement_date: Mapped[date | None] = mapped_column(Date)
