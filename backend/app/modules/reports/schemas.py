"""One table shape for every report, so the UI, Excel export and saved filters are shared.

Values travel as strings (money, quantities, percentages, dates) — never floats.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ColumnKind = Literal["text", "money", "qty", "int", "percent", "date"]


class Column(BaseModel):
    key: str
    label: str
    kind: ColumnKind = "text"


class ReportTable(BaseModel):
    key: str
    title: str
    columns: list[Column]
    # Each row: column key → value; optional "_level" (indent) and "_bold" for statements.
    rows: list[dict[str, Any]]
    totals: dict[str, Any] | None = None
    total_rows: int
    page: int
    page_size: int
    notes: list[str] = []


class ReportInfo(BaseModel):
    key: str
    title: str
    description: str
    group: str
    filters: list[str]


# --- query models (one per report) ---------------------------------------------------


class _Q(BaseModel):
    model_config = ConfigDict(extra="ignore")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=1000)
    branch_id: uuid.UUID | None = None


class RangeQ(_Q):
    date_from: date | None = None
    date_to: date | None = None


class SalesQ(RangeQ):
    group_by: Literal["day", "item", "group", "cashier", "register", "branch"] = "day"


class StockMovementQ(RangeQ):
    warehouse_id: uuid.UUID | None = None
    q: str | None = Field(default=None, max_length=100)
    only_moved: bool = True


class SlowQ(_Q):
    warehouse_id: uuid.UUID | None = None
    days: int = Field(default=30, ge=7, le=365)
    # Stock that lasts longer than this at the recent sales rate is "slow".
    cover_days: int = Field(default=90, ge=7, le=3650)


class ExpiryQ(_Q):
    warehouse_id: uuid.UUID | None = None
    days: int = Field(default=30, ge=0, le=365)


class AgingQ(_Q):
    side: Literal["debtors", "creditors"] = "debtors"
    as_of: date | None = None


class ShortageQ(RangeQ):
    group_by: Literal["cashier", "register", "shift"] = "cashier"


class StatementQ(_Q):
    fiscal_year_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class BalanceSheetQ(_Q):
    as_of: date | None = None


# --- dashboard ------------------------------------------------------------------------


class Kpi(BaseModel):
    net_sales: str
    gross_profit: str
    margin: str | None
    invoices: int
    returns: int
    average_basket: str | None


class DayPoint(BaseModel):
    date: date
    net_sales: str
    gross_profit: str
    invoices: int


class TopItem(BaseModel):
    item_id: uuid.UUID
    code: str
    name: str
    qty: str
    net_sales: str


class ExpiryAlert(BaseModel):
    """Lots (ADR-0027) by how soon they expire; days come from the settings."""

    expired: int
    urgent: int
    soon: int
    urgent_days: int
    warn_days: int


class Dashboard(BaseModel):
    date_from: date
    date_to: date
    current: Kpi
    previous: Kpi
    series: list[DayPoint]
    top_items: list[TopItem]
    payments: dict[str, str]
    inventory_value: str | None
    below_min_items: int | None
    expiry: ExpiryAlert | None = None
    receivables: str | None
    payables: str | None
    cash_shortage: str
    unknown_card_transactions: int
    generated_at: datetime


class DashboardQ(RangeQ):
    pass


# --- saved filters -----------------------------------------------------------------------


class SavedFilterIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    report: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)


class SavedFilterOut(BaseModel):
    id: uuid.UUID
    report: str
    name: str
    params: dict[str, Any]
    created_at: datetime
