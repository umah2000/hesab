from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

from app.core.money import QTY_PLACES, Money, parse_decimal

Qty = Annotated[
    Decimal,
    BeforeValidator(lambda v: parse_decimal(v, QTY_PLACES)),
    PlainSerializer(
        lambda d: format(d.quantize(QTY_PLACES), "f"), return_type=str, when_used="json"
    ),
]
COST_PLACES = Decimal("0.000001")
Cost = Annotated[
    Decimal,
    BeforeValidator(lambda v: parse_decimal(v, COST_PLACES)),
    PlainSerializer(
        lambda d: format(d.quantize(COST_PLACES), "f"), return_type=str, when_used="json"
    ),
]
# Documents a user writes by hand; sales and purchasing create the others themselves.
DocType = Literal["opening", "adjustment", "transfer", "count"]
AnyDocType = Literal[
    "opening",
    "adjustment",
    "transfer",
    "count",
    "sale",
    "sale_return",
    "purchase",
    "purchase_return",
]


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class UnitOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    allows_fraction: bool


class GroupOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    parent_id: uuid.UUID | None
    row_version: str


class GroupIn(_In):
    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=2, max_length=100)
    parent_id: uuid.UUID | None = None


class ItemUnitIO(_In):
    unit_id: uuid.UUID
    factor: Cost


class BarcodeIO(_In):
    barcode: str = Field(min_length=3, max_length=48, pattern=r"^[0-9A-Za-z\-.]+$")
    unit_id: uuid.UUID | None = None


class PriceIO(_In):
    price_list_id: uuid.UUID | None = None  # None = default list
    unit_id: uuid.UUID | None = None  # None = base unit
    price: Money


class ItemIn(_In):
    code: str = Field(min_length=1, max_length=32, pattern=r"^[0-9A-Za-z\-._]+$")
    name: str = Field(min_length=2, max_length=200)
    group_id: uuid.UUID | None = None
    base_unit_id: uuid.UUID
    item_type: Literal["goods", "service"] = "goods"
    is_weighted: bool = False
    scale_code: str | None = Field(default=None, max_length=8, pattern=r"^\d+$")
    track_expiry: bool = False
    vat_exempt: bool = False
    vat_rate: Annotated[Decimal, Field(ge=0, le=100)] | None = None
    tax_item_code: str | None = Field(default=None, max_length=32)
    min_qty: Qty | None = None
    max_qty: Qty | None = None
    is_active: bool = True
    units: list[ItemUnitIO] = []
    barcodes: list[BarcodeIO] = []
    prices: list[PriceIO] = []


class ItemImageOut(BaseModel):
    id: uuid.UUID
    # 0 = the main image.
    position: int
    width: int
    height: int


class ImageOrderIn(_In):
    ids: list[uuid.UUID] = Field(max_length=20)


class ItemOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    group_id: uuid.UUID | None
    group_name: str | None
    base_unit_id: uuid.UUID
    base_unit_name: str
    item_type: str
    is_weighted: bool
    scale_code: str | None
    track_expiry: bool
    vat_exempt: bool
    vat_rate: Decimal | None
    tax_item_code: str | None
    min_qty: Qty | None
    max_qty: Qty | None
    is_active: bool
    units: list[ItemUnitIO]
    barcodes: list[BarcodeIO]
    prices: list[PriceIO]
    stock_qty: Qty | None = None
    images: list[ItemImageOut] = []
    row_version: str


class ItemSummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    group_name: str | None
    base_unit_name: str
    is_weighted: bool
    is_active: bool
    barcode: str | None
    price: Money | None
    stock_qty: Qty
    # The main photo, if any (ADR-0022).
    image_id: uuid.UUID | None = None


class ItemQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    q: str | None = Field(default=None, max_length=60)
    group_id: uuid.UUID | None = None
    active: bool | None = None
    below_min: bool = False


class LookupOut(BaseModel):
    """What the POS needs after one scan."""

    item_id: uuid.UUID
    code: str
    name: str
    unit_id: uuid.UUID
    unit_name: str
    qty: Qty
    unit_price: Money | None
    line_price: Money | None
    source: Literal["barcode", "pack_barcode", "scale_weight", "scale_price", "code"]
    is_weighted: bool
    vat_exempt: bool
    vat_rate: Decimal | None


class ScaleRuleIn(_In):
    name: str = Field(min_length=2, max_length=100)
    prefix: str = Field(min_length=1, max_length=4, pattern=r"^\d+$")
    item_code_length: int = Field(ge=1, le=10)
    value_length: int = Field(ge=1, le=10)
    value_type: Literal["weight", "price"]
    value_decimals: int = Field(default=3, ge=0, le=4)
    # False: the scale prints 12 digits without the EAN-13 check digit.
    check_digit: bool = True
    is_active: bool = True


class ScaleRuleOut(ScaleRuleIn):
    id: uuid.UUID
    row_version: str


class PriceListOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    is_default: bool
    is_active: bool


class WarehouseIn(_In):
    branch_id: uuid.UUID
    code: str = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9]+$")
    name: str = Field(min_length=2, max_length=100)


class WarehouseOut(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    code: str
    name: str
    is_active: bool
    row_version: str


class StockLineIn(_In):
    item_id: uuid.UUID
    unit_id: uuid.UUID | None = None  # base unit
    qty: Qty
    unit_cost: Money | None = None
    expiry_date: date | None = None
    description: str | None = Field(default=None, max_length=300)


class StockDocIn(_In):
    doc_type: DocType
    warehouse_id: uuid.UUID
    dest_warehouse_id: uuid.UUID | None = None
    document_date: date
    description: str | None = Field(default=None, max_length=500)
    lines: list[StockLineIn] = Field(min_length=1, max_length=5000)


class StockLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_id: uuid.UUID
    unit_name: str
    qty: Qty
    base_qty: Qty
    unit_cost: Cost | None
    total_cost: Money | None
    system_qty: Qty | None
    expiry_date: date | None
    description: str | None


class StockDocOut(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    warehouse_id: uuid.UUID
    dest_warehouse_id: uuid.UUID | None
    doc_type: AnyDocType
    number: int | None
    document_date: date
    status: Literal["draft", "final"]
    description: str | None
    voucher_id: uuid.UUID | None
    voucher_number: int | None
    source_document_id: uuid.UUID | None
    total_value: Money | None
    finalized_at: datetime | None
    row_version: str
    lines: list[StockLineOut]


class StockDocSummary(BaseModel):
    id: uuid.UUID
    doc_type: AnyDocType
    number: int | None
    document_date: date
    status: Literal["draft", "final"]
    warehouse_id: uuid.UUID
    dest_warehouse_id: uuid.UUID | None
    description: str | None
    line_count: int


class BalanceRow(BaseModel):
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_name: str
    warehouse_id: uuid.UUID
    qty: Qty
    avg_cost: Cost
    value: Money
    min_qty: Qty | None
    below_min: bool


class KardexRow(BaseModel):
    document_id: uuid.UUID
    doc_type: AnyDocType
    number: int | None
    document_date: date
    qty_in: Qty
    qty_out: Qty
    value_in: Money
    value_out: Money
    balance_qty: Qty
    balance_value: Money
    avg_cost: Cost
