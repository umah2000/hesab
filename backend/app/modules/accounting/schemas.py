from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.money import Money

Level = Literal["group", "general", "subsidiary"]
Category = Literal["asset", "liability", "equity", "revenue", "expense"]
Nature = Literal["debit", "credit", "none"]
DetailKind = Literal["person", "bank", "cash", "cost_center", "project", "other"]


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# --- chart ------------------------------------------------------------------


class AccountOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    level: Level
    parent_id: uuid.UUID | None
    category: Category
    nature: Nature
    requires_detail: bool
    is_active: bool
    is_system: bool
    row_version: str


class AccountCreateIn(_In):
    code: str = Field(min_length=1, max_length=16, pattern=r"^\d+$")
    name: str = Field(min_length=2, max_length=150)
    parent_id: uuid.UUID | None = None
    # Only for groups; children inherit from their parent.
    category: Category | None = None
    nature: Nature | None = None
    requires_detail: bool = False


class AccountUpdateIn(_In):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    nature: Nature | None = None
    requires_detail: bool | None = None
    is_active: bool | None = None


class DetailAccountOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: DetailKind
    is_active: bool
    credit_limit: Money | None = None
    row_version: str


class DetailAccountCreateIn(_In):
    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=2, max_length=150)
    kind: DetailKind
    # Customers only; empty = no credit sales.
    credit_limit: Money | None = None


class DetailAccountUpdateIn(_In):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    is_active: bool | None = None
    # Sending null explicitly removes the limit (no credit sales).
    credit_limit: Money | None = None


# --- fiscal -----------------------------------------------------------------


class FiscalPeriodOut(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    start_date: date
    end_date: date
    is_locked: bool
    row_version: str


class FiscalYearOut(BaseModel):
    id: uuid.UUID
    title: str
    jalali_year: int
    start_date: date
    end_date: date
    status: Literal["open", "closed"]
    closed_at: datetime | None
    periods: list[FiscalPeriodOut]
    row_version: str


class FiscalYearCreateIn(_In):
    jalali_year: int = Field(ge=1390, le=1499)


class PeriodLockIn(_In):
    is_locked: bool


# --- vouchers ---------------------------------------------------------------


class VoucherLineIn(_In):
    account_id: uuid.UUID
    detail_account_id: uuid.UUID | None = None
    debit: Money = Field(default=Decimal("0.0000"))
    credit: Money = Field(default=Decimal("0.0000"))
    description: str | None = Field(default=None, max_length=300)


class VoucherIn(_In):
    branch_id: uuid.UUID
    document_date: date
    description: str | None = Field(default=None, max_length=500)
    lines: list[VoucherLineIn] = Field(min_length=1, max_length=500)


class VoucherLineOut(BaseModel):
    id: uuid.UUID
    line_no: int
    account_id: uuid.UUID
    account_code: str
    account_name: str
    detail_account_id: uuid.UUID | None
    detail_account_code: str | None
    detail_account_name: str | None
    debit: Money
    credit: Money
    description: str | None


class VoucherOut(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID | None
    fiscal_year_id: uuid.UUID
    number: int | None
    document_date: date
    status: Literal["draft", "final"]
    description: str | None
    source_type: str
    source_ref: str | None
    total_debit: Money
    total_credit: Money
    is_balanced: bool
    reversal_of_id: uuid.UUID | None
    reversed_by_id: uuid.UUID | None
    finalized_at: datetime | None
    created_at: datetime
    row_version: str
    lines: list[VoucherLineOut]


class VoucherSummaryOut(BaseModel):
    id: uuid.UUID
    number: int | None
    document_date: date
    status: Literal["draft", "final"]
    description: str | None
    source_type: str
    total_debit: Money
    total_credit: Money
    reversed_by_id: uuid.UUID | None
    reversal_of_id: uuid.UUID | None
    line_count: int


class VoucherQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    fiscal_year_id: uuid.UUID | None = None
    status: Literal["draft", "final"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    number: int | None = Field(default=None, ge=1)


class ReverseIn(_In):
    document_date: date | None = None
    description: str | None = Field(default=None, max_length=500)


# --- posting rules ----------------------------------------------------------


class PostingRuleOut(BaseModel):
    event_type: str
    event_label: str
    line_role: str
    role_label: str
    account_id: uuid.UUID | None
    account_code: str | None
    account_name: str | None


class PostingRuleIn(_In):
    event_type: str = Field(max_length=48)
    line_role: str = Field(max_length=32)
    account_id: uuid.UUID


# --- reports ----------------------------------------------------------------


class TrialBalanceQuery(BaseModel):
    fiscal_year_id: uuid.UUID
    level: Level = "subsidiary"
    date_from: date | None = None
    date_to: date | None = None
    include_closing: bool = False
    include_zero: bool = False


class TrialBalanceRow(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    level: Level
    opening_debit: Money
    opening_credit: Money
    turnover_debit: Money
    turnover_credit: Money
    balance_debit: Money
    balance_credit: Money


class TrialBalanceOut(BaseModel):
    rows: list[TrialBalanceRow]
    totals: TrialBalanceRow
    is_balanced: bool


class LedgerQuery(BaseModel):
    fiscal_year_id: uuid.UUID
    account_id: uuid.UUID
    detail_account_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=500)


class LedgerRow(BaseModel):
    voucher_id: uuid.UUID
    voucher_number: int
    document_date: date
    account_code: str
    detail_account_name: str | None
    description: str | None
    debit: Money
    credit: Money
    balance: Money


class LedgerOut(BaseModel):
    account_code: str
    account_name: str
    opening_balance: Money
    rows: list[LedgerRow]
    total: int
    page: int
    page_size: int
    period_debit: Money
    period_credit: Money
    closing_balance: Money
