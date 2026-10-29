"""Field sales API shapes (ADR-0018). Amounts are strings (ADR-0008)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    model_validator,
)

from app.core.money import Money
from app.modules.inventory.schemas import Qty

OrderStatus = Literal["submitted", "approved", "rejected", "invoiced", "delivered", "cancelled"]
# stocked / price / credit: why there was no order (ADR-0026).
Outcome = Literal["order", "no_order", "closed", "absent", "stocked", "price", "credit"]
Latitude = Annotated[Decimal, Field(ge=-90, le=90, max_digits=9, decimal_places=6)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180, max_digits=9, decimal_places=6)]


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
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    @field_serializer("latitude", "longitude")
    def _coord(self, v: Decimal | None) -> str | None:
        return None if v is None else _plain(v)


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
    # Only when the visitor allowed the app to read the phone's position.
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    accuracy_m: int | None = Field(default=None, ge=0, le=100000)


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
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    @field_serializer("latitude", "longitude")
    def _coord(self, v: Decimal | None) -> str | None:
        return None if v is None else _plain(v)


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


class AppBarcode(BaseModel):
    barcode: str
    # A pack barcode names the pack unit; None = the base unit.
    unit_id: uuid.UUID | None


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
    # For the camera scanner (ADR-0026).
    barcodes: list[AppBarcode] = []


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


# --- visitor app v2 (ADR-0026) -----------------------------------------------------------

Channel = Literal["mine", "visitor", "shop"]
Period = Literal["day", "week", "month"]
CollectionMethod = Literal["cash", "cheque", "transfer"]
RequestStatus = Literal["pending", "approved", "rejected"]


class HistoryInvoiceOut(BaseModel):
    """A final invoice of the customer, whoever sold it (view only)."""

    id: uuid.UUID
    number: int | None
    kind: Literal["sale", "return"]
    document_date: date
    grand_total: Money
    line_count: int
    # mine = from this visitor's order; visitor = another visitor's; shop = sold in the shop.
    channel: Channel
    visitor_name: str | None


class FrequentItemOut(BaseModel):
    item_id: uuid.UUID
    item_name: str
    times: int
    last_date: date


class CustomerHistoryOut(BaseModel):
    invoices: list[HistoryInvoiceOut]
    frequent_items: list[FrequentItemOut]


class InvoiceLineOut(BaseModel):
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_name: str
    qty: Qty
    unit_price: Money
    discount: Money
    tax: Money
    line_total: Money


class InvoiceDetailOut(HistoryInvoiceOut):
    subtotal: Money
    discount_total: Money
    tax_total: Money
    lines: list[InvoiceLineOut]


class OpenChequeOut(BaseModel):
    number: str
    amount: Money
    due_date: date
    status: str
    bank_name: str | None


class StatementRowOut(BaseModel):
    document_date: date
    description: str | None
    debit: Money
    credit: Money
    balance: Money


class CustomerAccountOut(BaseModel):
    balance: Money
    credit_limit: Money | None
    credit_unlimited: bool
    available: Money | None
    # Received cheques of this customer not cleared yet.
    open_cheques: list[OpenChequeOut]
    # Collections this visitor took that the treasury has not approved yet.
    pending_collections: Money
    # The last 60 days of the customer's account.
    statement: list[StatementRowOut]


class LocationIn(_In):
    latitude: Latitude
    longitude: Longitude


class NamedAmount(BaseModel):
    id: uuid.UUID
    name: str
    amount: Money
    count: int


class ReportFigures(BaseModel):
    ordered_amount: Money
    ordered_count: int
    invoiced_amount: Money
    invoiced_count: int
    customers: int
    average_order: Money
    rejected_count: int
    pending_count: int
    visits: int
    # Visits without an order, by reason (no_order, closed, absent, stocked, price, credit).
    no_order_reasons: dict[str, int]


class ReportOut(BaseModel):
    period: Period
    start: date
    end: date
    label: str
    current: ReportFigures
    previous: ReportFigures
    top_customers: list[NamedAmount]
    top_items: list[NamedAmount]
    # The month's target (the month of ``start``); progress counts invoiced amount.
    target: Money | None
    target_progress: Money | None


class CollectionIn(_In):
    id: uuid.UUID  # chosen on the phone; a resend returns the same record
    customer_id: uuid.UUID
    method: CollectionMethod
    amount: Money = Field(gt=0)
    collected_at: AwareDatetime
    reference: str | None = Field(default=None, max_length=60)
    cheque_number: str | None = Field(default=None, max_length=30)
    cheque_sayad_id: str | None = Field(default=None, pattern=r"^\d{16}$")
    cheque_bank: str | None = Field(default=None, max_length=100)
    cheque_drawer: str | None = Field(default=None, max_length=150)
    cheque_due_date: date | None = None
    note: str | None = Field(default=None, max_length=300)
    latitude: Latitude | None = None
    longitude: Longitude | None = None

    @model_validator(mode="after")
    def _instrument(self) -> CollectionIn:
        if self.method == "cheque" and (not self.cheque_number or not self.cheque_due_date):
            raise ValueError("شماره و تاریخ سررسید چک را وارد کنید")
        if self.method == "transfer" and not self.reference:
            raise ValueError("شماره‌ی پیگیری کارت‌به‌کارت را وارد کنید")
        return self


class CollectionOut(BaseModel):
    id: uuid.UUID
    visitor_id: uuid.UUID
    visitor_name: str
    customer_id: uuid.UUID
    customer_name: str
    method: CollectionMethod
    amount: Money
    collected_at: datetime
    received_at: datetime
    reference: str | None
    cheque_number: str | None
    cheque_sayad_id: str | None
    cheque_bank: str | None
    cheque_drawer: str | None
    cheque_due_date: date | None
    note: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    status: RequestStatus
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    treasury_document_id: uuid.UUID | None
    treasury_document_number: int | None
    row_version: str

    @field_serializer("latitude", "longitude")
    def _coord(self, v: Decimal | None) -> str | None:
        return None if v is None else _plain(v)


class CollectionApproveIn(_In):
    # The box (cash) or bank account (card-to-card) the money goes to; not for cheques.
    money_account_id: uuid.UUID | None = None
    document_date: date | None = None


class CustomerRequestIn(_In):
    id: uuid.UUID
    name: str = Field(min_length=2, max_length=150)
    owner_name: str | None = Field(default=None, max_length=150)
    mobile: str | None = Field(default=None, max_length=15)
    phone: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=500)
    national_id: str | None = Field(default=None, max_length=11, pattern=r"^\d{10,11}$")
    economic_code: str | None = Field(default=None, max_length=16, pattern=r"^\d{10,16}$")
    visit_weekday: int | None = Field(default=None, ge=0, le=6)
    note: str | None = Field(default=None, max_length=300)
    latitude: Latitude | None = None
    longitude: Longitude | None = None


class CustomerRequestOut(BaseModel):
    id: uuid.UUID
    visitor_id: uuid.UUID
    visitor_name: str
    name: str
    owner_name: str | None
    mobile: str | None
    phone: str | None
    city: str | None
    address: str | None
    national_id: str | None
    economic_code: str | None
    visit_weekday: int | None
    note: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    status: RequestStatus
    created_at: datetime
    decided_by_name: str | None
    decided_at: datetime | None
    decision_note: str | None
    party_id: uuid.UUID | None
    party_code: str | None
    row_version: str

    @field_serializer("latitude", "longitude")
    def _coord(self, v: Decimal | None) -> str | None:
        return None if v is None else _plain(v)


class CustomerRequestApproveIn(_In):
    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    group_id: uuid.UUID | None = None
    credit_limit: Money | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=300)


class RequestQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    status: RequestStatus | None = None
    visitor_id: uuid.UUID | None = None


class TargetIn(_In):
    amount: Money = Field(ge=0)


class TargetOut(BaseModel):
    visitor_id: uuid.UUID
    visitor_name: str
    jalali_year: int
    jalali_month: int
    amount: Money | None
    invoiced: Money
    row_version: str | None


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    ref_type: str | None
    ref_id: uuid.UUID | None
    created_at: datetime
    read_at: datetime | None


class ReadIn(_In):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    all: bool = False
