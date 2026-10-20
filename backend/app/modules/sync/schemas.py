"""Offline sync contract between the register agent and the server (sync/protocol.md).

Amounts are strings (ADR-0008). An offline sale carries the lines exactly as the
register priced and printed them; the server checks the arithmetic, never reprices it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

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


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


def _plain(v: Decimal) -> str:
    return format(v.normalize(), "f")


# --- snapshot (server → agent) -------------------------------------------------


class SnapItem(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    group_id: uuid.UUID | None
    base_unit_id: uuid.UUID
    item_type: str
    is_weighted: bool
    scale_code: str | None
    vat_exempt: bool
    vat_rate: Decimal | None
    stock: Qty | None

    @field_serializer("vat_rate")
    def _vr(self, v: Decimal | None) -> str | None:
        return None if v is None else _plain(v)


class SnapUnit(BaseModel):
    id: uuid.UUID
    name: str
    allows_fraction: bool


class SnapFactor(BaseModel):
    item_id: uuid.UUID
    unit_id: uuid.UUID
    factor: Decimal

    @field_serializer("factor")
    def _f(self, v: Decimal) -> str:
        return _plain(v)


class SnapPrice(BaseModel):
    item_id: uuid.UUID
    unit_id: uuid.UUID
    price: Money


class SnapBarcode(BaseModel):
    barcode: str
    item_id: uuid.UUID
    unit_id: uuid.UUID | None


class SnapScaleRule(BaseModel):
    prefix: str
    item_code_length: int
    value_type: str
    value_decimals: int


class SnapPromotion(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    value: Money
    item_id: uuid.UUID | None
    group_id: uuid.UUID | None
    starts_on: date
    ends_on: date


class SnapSettings(BaseModel):
    organization_name: str
    timezone: str
    display_currency: str
    default_vat_rate: Decimal
    prices_include_vat: bool
    cashier_discount_limit: Decimal
    negative_stock_policy: str
    receipt_header: str | None
    receipt_footer: str | None

    @field_serializer("default_vat_rate", "cashier_discount_limit")
    def _r(self, v: Decimal) -> str:
        return _plain(v)


class SnapRegister(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    branch_id: uuid.UUID
    branch_name: str
    warehouse_id: uuid.UUID


class SnapShift(BaseModel):
    """The register's open shift: offline sales are only possible inside it."""

    id: uuid.UUID
    user_id: uuid.UUID
    username: str
    user_name: str
    opened_at: datetime
    opening_cash: Money
    # The cashier's permissions when the snapshot was taken (checked again on sync).
    permissions: list[str]


class SnapshotOut(BaseModel):
    version: str
    generated_at: datetime
    # After this the register stops selling offline: prices and stock are too old.
    valid_until: datetime
    # Offline receipt numbers start with this; the server rejects any other prefix.
    number_prefix: str
    cash_register: SnapRegister
    shift: SnapShift | None
    settings: SnapSettings
    units: list[SnapUnit]
    items: list[SnapItem]
    factors: list[SnapFactor]
    prices: list[SnapPrice]
    barcodes: list[SnapBarcode]
    scale_rules: list[SnapScaleRule]
    promotions: list[SnapPromotion]


# --- push (agent → server) -----------------------------------------------------


class OfflineLineIn(_In):
    item_id: uuid.UUID
    unit_id: uuid.UUID
    qty: Qty = Field(gt=0)
    unit_price: Money = Field(ge=0)
    price_source: Literal["list", "scale"]
    gross: Money = Field(ge=0)
    promotion_id: uuid.UUID | None = None
    promotion_discount: Money = Field(default=Decimal(0), ge=0)
    manual_discount: Money = Field(default=Decimal(0), ge=0)
    vat_exempt: bool
    vat_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    tax: Money = Field(ge=0)
    line_total: Money = Field(ge=0)
    scanned_barcode: str | None = Field(default=None, max_length=48)


class OfflinePaymentIn(_In):
    # Offline: no credit (no balance to check) and no card-reader integration;
    # the card is paid on a stand-alone reader and its tracking number typed in.
    method: Literal["cash", "card"]
    amount: Money = Field(gt=0)
    card_reference: str | None = Field(default=None, pattern=r"^[0-9]{4,32}$")


class OfflineSaleIn(_In):
    id: uuid.UUID  # = operation id = invoice id
    device_number: str = Field(pattern=r"^[A-Z0-9]{4,12}-[0-9]{1,12}$")
    sold_at: AwareDatetime
    cash_register_id: uuid.UUID
    shift_id: uuid.UUID
    user_id: uuid.UUID
    snapshot_version: str = Field(max_length=64)
    # The setting the register priced with (taken from its snapshot).
    prices_include_vat: bool
    lines: list[OfflineLineIn] = Field(min_length=1, max_length=500)
    subtotal: Money
    discount_total: Money
    tax_total: Money
    grand_total: Money
    payments: list[OfflinePaymentIn] = Field(min_length=1, max_length=10)
    cash_tendered: Money | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=300)


class OfflineRemovalIn(_In):
    """A scanned line taken off the cart while offline (audited, ADR-0017)."""

    cash_register_id: uuid.UUID
    shift_id: uuid.UUID
    user_id: uuid.UUID
    item_id: uuid.UUID
    qty: Qty = Field(gt=0)
    line_total: Money = Field(ge=0)
    removed_at: AwareDatetime


class OfflineOpIn(_In):
    id: uuid.UUID
    type: Literal["sale", "line_removal"]
    local_time: AwareDatetime
    sale: OfflineSaleIn | None = None
    removal: OfflineRemovalIn | None = None

    @model_validator(mode="after")
    def _one(self) -> OfflineOpIn:
        if (self.type == "sale") != (self.sale is not None) or (self.type == "line_removal") != (
            self.removal is not None
        ):
            raise ValueError("operation body does not match its type")
        return self


class PushIn(BaseModel):
    # Each operation is validated on its own, so one bad entry never blocks the queue.
    ops: list[dict[str, Any]] = Field(max_length=50)


class PushResult(BaseModel):
    id: uuid.UUID | None
    status: Literal["applied", "rejected", "conflict", "resolved", "discarded"]
    code: str | None
    message: str | None
    invoice_id: uuid.UUID | None
    number: int | None


class PushOut(BaseModel):
    results: list[PushResult]


# --- administration -----------------------------------------------------------


class OperationOut(BaseModel):
    id: uuid.UUID
    device_id: uuid.UUID
    device_name: str
    register_name: str | None
    op_type: str
    status: str
    device_number: str | None
    sold_at: datetime | None
    local_time: datetime
    received_at: datetime
    cashier_name: str | None
    grand_total: Money | None
    code: str | None
    message: str | None
    price_difference: Money | None
    invoice_id: uuid.UUID | None
    invoice_number: int | None
    resolved_by_name: str | None
    resolved_at: datetime | None
    resolution_note: str | None
    row_version: str


class OperationQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    status: Literal["applied", "rejected", "conflict", "resolved", "discarded", "open"] | None = (
        None
    )
    device_id: uuid.UUID | None = None


class ResolveIn(_In):
    action: Literal["apply", "discard"]
    note: str = Field(min_length=2, max_length=500)
