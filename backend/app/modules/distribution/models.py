"""Field sales (visitors): assigned customers, visits and sales orders — ADR-0018.

An order is a request, not a financial document: it is priced by the server when it
arrives, approved in the back office (credit checked), then turned into an ordinary
credit sales invoice, which is where stock and the books move.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
RATE = Numeric(5, 2)

ORDER_STATUSES = ("submitted", "approved", "rejected", "invoiced", "delivered", "cancelled")
VISIT_OUTCOMES = ("order", "no_order", "closed", "absent")


class Visitor(EntityMixin, ActorMixin, VersionedMixin, Base):
    """A user who sells in the field with the Android app."""

    __tablename__ = "visitor"
    __table_args__ = (UniqueConstraint("user_id"), UniqueConstraint("code"))

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    code: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Unicode(300))


class VisitorCustomer(EntityMixin, ActorMixin, Base):
    """A customer assigned to a visitor, with the weekday of the regular visit."""

    __tablename__ = "visitor_customer"
    __table_args__ = (
        UniqueConstraint("visitor_id", "customer_id"),
        # 0 = Saturday … 6 = Friday (the Iranian week); NULL = no fixed day.
        CheckConstraint("visit_weekday BETWEEN 0 AND 6", name="visit_weekday"),
        Index("ix_visitor_customer_customer", "customer_id"),
    )

    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitor.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detail_account.id"))
    visit_weekday: Mapped[int | None] = mapped_column(Integer)


class SalesOrder(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "sales_order"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted','approved','rejected','invoiced','delivered','cancelled')",
            name="status",
        ),
        Index("ix_sales_order_status", "status", "received_at"),
        Index("ix_sales_order_visitor", "visitor_id", "ordered_at"),
        Index(
            "uq_sales_order_number",
            "branch_id",
            "fiscal_year_id",
            "number",
            unique=True,
            mssql_where=text("number IS NOT NULL"),
        ),
    )

    # id = chosen by the app when the order is written (Idempotency-Key).
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branch.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse.id"))
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fiscal_year.id"))
    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitor.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detail_account.id"))
    number: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="submitted")
    # When the visitor wrote it (phone clock) and when the server got it.
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    discount_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    tax_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    grand_total: Mapped[Decimal] = mapped_column(MONEY)
    # The estimate the phone showed (it never decides the price).
    client_total: Mapped[Decimal | None] = mapped_column(MONEY)
    note: Mapped[str | None] = mapped_column(Unicode(300))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Unicode(300))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_invoice.id"))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))

    lines: Mapped[list[SalesOrderLine]] = relationship(
        back_populates="order", order_by="SalesOrderLine.line_no", cascade="all, delete-orphan"
    )


class SalesOrderLine(EntityMixin, Base):
    __tablename__ = "sales_order_line"
    __table_args__ = (
        UniqueConstraint("order_id", "line_no"),
        CheckConstraint("qty > 0", name="qty"),
        Index("ix_sales_order_line_item", "item_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_order.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("item.id"))
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("unit.id"))
    qty: Mapped[Decimal] = mapped_column(QTY)
    base_qty: Mapped[Decimal] = mapped_column(QTY)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    gross: Mapped[Decimal] = mapped_column(MONEY)
    promotion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("promotion.id"))
    promotion_discount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    vat_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal(0))
    tax: Mapped[Decimal] = mapped_column(MONEY, default=Decimal(0))
    revenue: Mapped[Decimal] = mapped_column(MONEY)
    line_total: Mapped[Decimal] = mapped_column(MONEY)

    order: Mapped[SalesOrder] = relationship(back_populates="lines")


class Visit(EntityMixin, Base):
    """A visit logged by the visitor (id chosen on the phone; sent once)."""

    __tablename__ = "visit"
    __table_args__ = (
        CheckConstraint("outcome IN ('order','no_order','closed','absent')", name="outcome"),
        Index("ix_visit_visitor", "visitor_id", "visited_at"),
    )

    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitor.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detail_account.id"))
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(Unicode(300))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_order.id"))
