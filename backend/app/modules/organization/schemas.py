from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    display_currency: Literal["IRR", "IRT"]
    timezone: str
    negative_stock_policy: Literal["deny", "warn", "allow"]
    last_offsite_backup_at: datetime | None
    default_vat_rate: Decimal
    prices_include_vat: bool
    cashier_discount_limit: Decimal
    backup_warning_days: int
    receipt_header: str | None
    receipt_footer: str | None
    invoice_paper: Literal["thermal", "a5", "a4"] = "thermal"
    about: str | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    # Changes with every new logo (cache key); None = no logo.
    logo_version: str | None = None
    row_version: str

    @field_serializer("default_vat_rate", "cashier_discount_limit")
    def _rate(self, v: Decimal) -> str:
        return format(v.normalize(), "f")


class OrganizationUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=200)
    display_currency: Literal["IRR", "IRT"] | None = None
    negative_stock_policy: Literal["deny", "warn", "allow"] | None = None
    default_vat_rate: (
        Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None
    ) = None
    prices_include_vat: bool | None = None
    cashier_discount_limit: (
        Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None
    ) = None
    backup_warning_days: int | None = Field(default=None, ge=1, le=60)
    receipt_header: str | None = Field(default=None, max_length=500)
    receipt_footer: str | None = Field(default=None, max_length=500)
    invoice_paper: Literal["thermal", "a5", "a4"] | None = None
    about: str | None = Field(default=None, max_length=2000)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=300)
    website: str | None = Field(
        default=None, max_length=200, pattern=r"^$|^(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?$"
    )


class BranchOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    address: str | None
    is_active: bool
    row_version: str


class BranchCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9]+$")
    name: str = Field(min_length=2, max_length=150)
    address: str | None = Field(default=None, max_length=500)


class BranchUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=150)
    address: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class CashRegisterOut(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    code: str
    name: str
    is_active: bool
    row_version: str


class CashRegisterCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    branch_id: uuid.UUID
    code: str = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9]+$")
    name: str = Field(min_length=2, max_length=100)


class CashRegisterUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=100)
    is_active: bool | None = None
