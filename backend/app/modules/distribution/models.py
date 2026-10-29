"""Field sales (visitors): assigned customers, visits and sales orders — ADR-0018.

An order is a request, not a financial document: it is priced by the server when it
arrives, approved in the back office (credit checked), then turned into an ordinary
credit sales invoice, which is where stock and the books move.
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

ORDER_STATUSES = ("submitted", "approved", "rejected", "invoiced", "delivered", "cancelled")
# stocked / price / credit: why there was no order (ADR-0026).
VISIT_OUTCOMES = ("order", "no_order", "closed", "absent", "stocked", "price", "credit")
COLLECTION_METHODS = ("cash", "cheque", "transfer")
REQUEST_STATUSES = ("pending", "approved", "rejected")
COORD = Numeric(9, 6)


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
        CheckConstraint(
            "outcome IN ('order','no_order','closed','absent','stocked','price','credit')",
            name="outcome",
        ),
        Index("ix_visit_visitor", "visitor_id", "visited_at"),
    )

    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitor.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detail_account.id"))
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(Unicode(300))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_order.id"))
    # The phone's position, only when the visitor allowed it.
    latitude: Mapped[Decimal | None] = mapped_column(COORD)
    longitude: Mapped[Decimal | None] = mapped_column(COORD)
    accuracy_m: Mapped[int | None] = mapped_column(Integer)


class VisitorTarget(EntityMixin, ActorMixin, VersionedMixin, Base):
    """The sales target of a visitor for one Jalali month; progress = invoiced amount."""

    __tablename__ = "visitor_target"
    __table_args__ = (
        UniqueConstraint("visitor_id", "jalali_year", "jalali_month"),
        CheckConstraint("jalali_month BETWEEN 1 AND 12", name="month"),
        CheckConstraint("amount >= 0", name="amount"),
    )

    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitor.id"))
    jalali_year: Mapped[int] = mapped_column(Integer)
    jalali_month: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(MONEY)


class VisitorCollection(EntityMixin, ActorMixin, VersionedMixin, Base):
    """Money a visitor took from a customer: a request until the treasury approves it.

    Approval creates an ordinary treasury receipt (the voucher comes from its posting
    rules); until then the customer's balance does not change (ADR-0026).
    """

    __tablename__ = "visitor_collection"
    __table_args__ = (
        CheckConstraint("method IN ('cash','cheque','transfer')", name="method"),
        CheckConstraint("status IN ('pending','approved','rejected')", name="status"),
        CheckConstraint("amount > 0", name="amount"),
        Index("ix_visitor_collection_status", "status", "collected_at"),
        Index("ix_visitor_collection_visitor", "visitor_id", "collected_at"),
    )

    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitor.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("detail_account.id"))
    method: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Card-to-card: the tracking number. Cheque: number, Sayad id, bank, drawer, due date.
    reference: Mapped[str | None] = mapped_column(Unicode(60))
    cheque_number: Mapped[str | None] = mapped_column(String(30))
    cheque_sayad_id: Mapped[str | None] = mapped_column(String(16))
    cheque_bank: Mapped[str | None] = mapped_column(Unicode(100))
    cheque_drawer: Mapped[str | None] = mapped_column(Unicode(150))
    cheque_due_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Unicode(300))
    latitude: Mapped[Decimal | None] = mapped_column(COORD)
    longitude: Mapped[Decimal | None] = mapped_column(COORD)
    status: Mapped[str] = mapped_column(String(8), default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Unicode(300))
    treasury_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("treasury_document.id")
    )


class CustomerRequest(EntityMixin, ActorMixin, VersionedMixin, Base):
    """A new shop the visitor found; the back office turns it into a party (ADR-0026)."""

    __tablename__ = "customer_request"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected')", name="status"),
        CheckConstraint("visit_weekday BETWEEN 0 AND 6", name="visit_weekday"),
        Index("ix_customer_request_status", "status", "created_at"),
    )

    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitor.id"))
    name: Mapped[str] = mapped_column(Unicode(150))
    owner_name: Mapped[str | None] = mapped_column(Unicode(150))
    mobile: Mapped[str | None] = mapped_column(String(15))
    phone: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(Unicode(60))
    address: Mapped[str | None] = mapped_column(Unicode(500))
    national_id: Mapped[str | None] = mapped_column(String(11))
    economic_code: Mapped[str | None] = mapped_column(String(16))
    visit_weekday: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Unicode(300))
    latitude: Mapped[Decimal | None] = mapped_column(COORD)
    longitude: Mapped[Decimal | None] = mapped_column(COORD)
    status: Mapped[str] = mapped_column(String(8), default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Unicode(300))
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("party.id"))


class VisitorNotification(EntityMixin, Base):
    """Something the visitor should hear about; the app fetches them on every sync."""

    __tablename__ = "visitor_notification"
    __table_args__ = (Index("ix_visitor_notification_visitor", "visitor_id", "created_at"),)

    visitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("visitor.id"))
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(Unicode(150))
    body: Mapped[str | None] = mapped_column(Unicode(300))
    ref_type: Mapped[str | None] = mapped_column(String(24))
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UNIQUEIDENTIFIER)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
