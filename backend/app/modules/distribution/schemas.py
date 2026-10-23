"""Field sales API shapes (ADR-0018). Amounts are strings (ADR-0008)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer

from app.core.money import Money
from app.modules.inventory.schemas import Qty

OrderStatus = Literal["submitted", "approved", "rejected", "invoiced", "delivered", "cancelled"]
Outcome = Literal["order", "no_order", "closed", "absent"]


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


def _plain(v: Decimal) -> str:
    return format(v.normalize(), "f")


# --- visitors (back office) ------------------------------------------------------------


class VisitorIn(_In):
    user_id: uuid.UUID
    branch_id: uuid.UUID
    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9_-]+$")
    note: str | None = Field(default=None, max_length=300)


class VisitorUpdateIn(_In):
    branch_id: uuid.UUID
    is_active: bool
    note: str | None = Field(default=None, max_length=300)


class VisitorOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    name: str
    branch_id: uuid.UUID
    branch_name: str
    code: str
    is_active: bool
    note: str | None
    customer_count: int
    last_seen_at: datetime | None
    row_version: str


class CandidateOut(BaseModel):
    """An active user with the visitor role (who may become a visitor)."""

    user_id: uuid.UUID
    username: str
    full_name: str
    visitor_id: uuid.UUID | None


class AssignmentIn(_In):
    customer_id: uuid.UUID
    # 0 = Saturday … 6 = Friday; None = no fixed day.
    visit_weekday: int | None = Field(default=None, ge=0, le=6)


class AssignmentsIn(_In):
    customers: list[AssignmentIn] = Field(max_length=20000)


class AssignedCustomerOut(BaseModel):
    customer_id: uuid.UUID
    code: str
    name: str
    phone: str | None
    address: str | None
    visit_weekday: int | None
    credit_limit: Money | None
    # Credit sales with no limit (available is then None too).
    credit_unlimited: bool = False
    balance: Money
    # Credit still available (None = no credit sales, or unlimited).
    available: Money | None


# --- orders ------------------------------------------------------------------------------


class OrderLineIn(_In):
    item_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    qty: Qty = Field(gt=0)


class QuoteIn(_In):
    customer_id: uuid.UUID
    lines: list[OrderLineIn] = Field(min_length=1, max_length=300)


class OrderIn(QuoteIn):
    id: uuid.UUID  # chosen on the phone; a resend returns the same order
    ordered_at: AwareDatetime
    note: str | None = Field(default=None, max_length=300)
    # The estimate the phone showed; only compared, never used.
    client_total: Money | None = None


class OrderLineOut(BaseModel):
    line_no: int
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_id: uuid.UUID
    unit_name: str
    qty: Qty
    unit_price: Money
    gross: Money
    promotion_name: str | None
    promotion_discount: Money
    vat_rate: Decimal
    tax: Money
    line_total: Money
    stock_qty: Qty | None = None

    @field_serializer("vat_rate")
    def _vr(self, v: Decimal) -> str:
        return _plain(v)


class QuoteOut(BaseModel):
    lines: list[OrderLineOut]
    subtotal: Money
    discount_total: Money
    tax_total: Money
    grand_total: Money
    warnings: list[str]
    credit_limit: Money | None
    credit_unlimited: bool = False
    balance: Money
    available_after: Money | None


class OrderOut(BaseModel):
    id: uuid.UUID
    number: int | None
    status: OrderStatus
    branch_id: uuid.UUID
    visitor_id: uuid.UUID
    visitor_name: str
    customer_id: uuid.UUID
    customer_name: str
    ordered_at: datetime
    received_at: datetime
    subtotal: Money
    discount_total: Money
    tax_total: Money
    grand_total: Money
    client_total: Money | None
    # The phone's estimate differed from the server's price.
    price_changed: bool
    note: str | None
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    invoice_id: uuid.UUID | None
    invoice_number: int | None
    delivered_at: datetime | None
    lines: list[OrderLineOut]
    warnings: list[str] = []
    row_version: str


class OrderSummaryOut(BaseModel):
    id: uuid.UUID
    number: int | None
    status: OrderStatus
    visitor_name: str
    customer_name: str
    ordered_at: datetime
    received_at: datetime
    grand_total: Money
    price_changed: bool
    invoice_number: int | None


class OrderQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    status: OrderStatus | Literal["open"] | None = None
    visitor_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class DecisionIn(_In):
    note: str | None = Field(default=None, max_length=300)


class RejectIn(_In):
    note: str = Field(min_length=2, max_length=300)


class InvoiceOrderIn(_In):
    # The register whose daily report carries the credit sale (e.g. «فروش ویزیتوری»).
    cash_register_id: uuid.UUID


# --- visits --------------------------------------------------------------------------------


class VisitIn(_In):
    id: uuid.UUID
    customer_id: uuid.UUID
    visited_at: AwareDatetime
    outcome: Outcome
    note: str | None = Field(default=None, max_length=300)
    order_id: uuid.UUID | None = None


class VisitOut(BaseModel):
    id: uuid.UUID
    visitor_name: str
    customer_id: uuid.UUID
    customer_name: str
    visited_at: datetime
    received_at: datetime
    outcome: Outcome
    note: str | None
    order_id: uuid.UUID | None


# --- the app's offline data ----------------------------------------------------------------


class AppUnit(BaseModel):
    unit_id: uuid.UUID
    name: str
    factor: Decimal
    price: Money | None
    allows_fraction: bool

    @field_serializer("factor")
    def _f(self, v: Decimal) -> str:
        return _plain(v)


class AppItem(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    group_name: str | None
    base_unit_id: uuid.UUID
    units: list[AppUnit]
    stock: Qty | None
    vat_exempt: bool
    # Photo ids, main first (ADR-0022): /distribution/mobile/images/<id>?size=thumb|large.
    image_ids: list[uuid.UUID] = []


class AppSettings(BaseModel):
    organization_name: str
    display_currency: str
    prices_include_vat: bool
    default_vat_rate: Decimal

    @field_serializer("default_vat_rate")
    def _r(self, v: Decimal) -> str:
        return _plain(v)


class AppVisitor(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    branch_name: str


class BootstrapOut(BaseModel):
    """What the phone keeps for working without a connection (prices are an estimate)."""

    version: str
    generated_at: datetime
    visitor: AppVisitor
    settings: AppSettings
    customers: list[AssignedCustomerOut]
    items: list[AppItem]
