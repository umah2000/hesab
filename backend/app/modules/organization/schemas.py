from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    display_currency: Literal["IRR", "IRT"]
    timezone: str
    negative_stock_policy: Literal["deny", "warn", "allow"]
    last_offsite_backup_at: datetime | None
    row_version: str


class OrganizationUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=200)
    display_currency: Literal["IRR", "IRT"] | None = None
    negative_stock_policy: Literal["deny", "warn", "allow"] | None = None


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
