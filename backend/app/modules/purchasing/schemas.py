from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.money import Money
from app.modules.inventory.schemas import Qty


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# --- orders -----------------------------------------------------------------


class OrderLineIn(_In):
    item_id: uuid.UUID
    # Empty = the item's base unit.
    unit_id: uuid.UUID | None = None
    qty: Qty = Field(gt=0)
    unit_cost: Money | None = Field(default=None, ge=0)


class OrderIn(_In):
    warehouse_id: uuid.UUID
    supplier_id: uuid.UUID
    order_date: date
    expected_date: date | None = None
    note: str | None = Field(default=None, max_length=500)
    lines: list[OrderLineIn] = Field(min_length=1, max_length=500)


class OrderLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_id: uuid.UUID
    unit_name: str
    qty: Qty
    base_qty: Qty
    unit_cost: Money | None
    # Received on final purchase invoices, in the base unit.
    received_base_qty: Qty


class OrderOut(BaseModel):
    id: uuid.UUID
    number: int | None
    status: str
    branch_id: uuid.UUID
    warehouse_id: uuid.UUID
    warehouse_name: str
    supplier_id: uuid.UUID
    supplier_name: str
    order_date: date
    expected_date: date | None
    note: str | None
    estimated_total: Money
    lines: list[OrderLineOut]
    created_at: datetime
    row_version: str


class OrderSummary(BaseModel):
    id: uuid.UUID
    number: int | None
    status: str
    supplier_name: str
    warehouse_name: str
    order_date: date
    expected_date: date | None
    estimated_total: Money


class OrderQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    status: Literal["draft", "approved", "closed", "cancelled"] | None = None
    supplier_id: uuid.UUID | None = None


# --- invoices ---------------------------------------------------------------


class InvoiceLineIn(_In):
    item_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    qty: Qty = Field(gt=0)
    # Supplier price per line unit, excluding VAT.
    unit_cost: Money = Field(ge=0)
    discount: Money = Field(default=Decimal(0), ge=0)
    # Empty = the item's VAT rate (or the organisation default); exempt items carry 0.
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100)
    expiry_date: date | None = None
    order_line_id: uuid.UUID | None = None


class ChargeIn(_In):
    description: str = Field(min_length=2, max_length=200)
    amount: Money = Field(gt=0)
    # Empty = billed by the invoice's supplier; otherwise owed to this party (carrier…).
    payee_id: uuid.UUID | None = None


class InvoiceIn(_In):
    warehouse_id: uuid.UUID
    supplier_id: uuid.UUID
    document_date: date
    supplier_invoice_no: str | None = Field(default=None, max_length=40)
    supplier_invoice_date: date | None = None
    # Empty = document date + the supplier's payment terms.
    due_date: date | None = None
    order_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)
    lines: list[InvoiceLineIn] = Field(min_length=1, max_length=500)
    charges: list[ChargeIn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _due(self) -> InvoiceIn:
        if self.due_date is not None and self.due_date < self.document_date:
            raise ValueError("سررسید نمی‌تواند پیش از تاریخ سند باشد")
        return self


class ReturnLineIn(_In):
    original_line_id: uuid.UUID
    qty: Qty = Field(gt=0)


class ReturnIn(_In):
    document_date: date
    reason: str = Field(min_length=2, max_length=500)
    lines: list[ReturnLineIn] = Field(min_length=1, max_length=500)


class InvoiceLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit_id: uuid.UUID
    unit_name: str
    qty: Qty
    base_qty: Qty
    unit_cost: Money
    gross: Money
    discount: Money
    net: Money
    vat_rate: Decimal
    tax: Money
    landed: Money
    total_cost: Money
    expiry_date: date | None
    order_line_id: uuid.UUID | None
    original_line_id: uuid.UUID | None
    # For returns of this line: what is still returnable.
    returnable_qty: Qty | None


class ChargeOut(BaseModel):
    id: uuid.UUID
    line_no: int
    description: str
    amount: Money
    payee_id: uuid.UUID | None
    payee_name: str


class InvoiceOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    number: int | None
    branch_id: uuid.UUID
    warehouse_id: uuid.UUID
    warehouse_name: str
    supplier_id: uuid.UUID
    supplier_name: str
    document_date: date
    supplier_invoice_no: str | None
    supplier_invoice_date: date | None
    due_date: date | None
    order_id: uuid.UUID | None
    order_number: int | None
    original_invoice_id: uuid.UUID | None
    original_number: int | None
    subtotal: Money
    discount_total: Money
    tax_total: Money
    charges_total: Money
    grand_total: Money
    cost_total: Money
    note: str | None
    voucher_id: uuid.UUID | None
    stock_document_id: uuid.UUID | None
    lines: list[InvoiceLineOut]
    charges: list[ChargeOut]
    warnings: list[str] = []
    created_at: datetime
    finalized_at: datetime | None
    row_version: str


class InvoiceSummary(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    number: int | None
    supplier_id: uuid.UUID
    supplier_name: str
    supplier_invoice_no: str | None
    document_date: date
    due_date: date | None
    grand_total: Money


class InvoiceQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    kind: Literal["invoice", "return"] | None = None
    status: Literal["draft", "final"] | None = None
    supplier_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    q: str | None = Field(default=None, max_length=40)


class PriceHistoryOut(BaseModel):
    invoice_id: uuid.UUID
    number: int | None
    document_date: date
    supplier_name: str
    qty: Qty
    unit_name: str
    unit_cost: Money
    # Per base unit, after discount and landed costs: what entered stock.
    base_unit_cost: Money


class DueOut(BaseModel):
    supplier_id: uuid.UUID
    supplier_name: str
    invoice_id: uuid.UUID
    number: int | None
    supplier_invoice_no: str | None
    document_date: date
    due_date: date
    grand_total: Money
    # Still unpaid, assuming payments settle the oldest invoices first.
    outstanding: Money
    # The supplier's current payable balance (all documents), positive = we owe.
    supplier_balance: Money
    overdue_days: int
