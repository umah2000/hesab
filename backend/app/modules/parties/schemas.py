from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.money import _FA, Money

PartyType = Literal["person", "company"]


def digits(v: str | None) -> str | None:
    if v is None:
        return None
    s = re.sub(r"[\s\-]", "", v.translate(_FA))
    return s or None


def valid_national_code(code: str) -> bool:
    """کد ملی اشخاص حقیقی: ۱۰ رقم با رقم کنترل."""
    if not re.fullmatch(r"\d{10}", code) or len(set(code)) == 1:
        return False
    total = sum(int(code[i]) * (10 - i) for i in range(9))
    r = total % 11
    check = int(code[9])
    return check == r if r < 2 else check == 11 - r


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PartyFields(_In):
    name: str = Field(min_length=2, max_length=150)
    party_type: PartyType = "person"
    is_customer: bool = True
    is_supplier: bool = False
    group_id: uuid.UUID | None = None
    national_id: str | None = Field(default=None, max_length=20)
    economic_code: str | None = Field(default=None, max_length=20)
    registration_no: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)
    mobile: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    postal_code: str | None = Field(default=None, max_length=12)
    city: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=500)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    # Customers only; empty = no credit sales, unless credit_unlimited (no limit at all).
    credit_limit: Money | None = Field(default=None, ge=0)
    credit_unlimited: bool = False

    @field_validator(
        "national_id", "economic_code", "registration_no", "phone", "mobile", "postal_code"
    )
    @classmethod
    def _digits(cls, v: str | None) -> str | None:
        return digits(v)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v.startswith("+98"):
            v = "0" + v[3:]
        elif v.startswith("98") and len(v) == 12:
            v = "0" + v[2:]
        if not re.fullmatch(r"09\d{9}", v):
            raise ValueError("شماره همراه باید ۱۱ رقم و با ۰۹ شروع شود")
        return v

    @field_validator("postal_code")
    @classmethod
    def _postal(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{10}", v):
            raise ValueError("کد پستی ۱۰ رقم است")
        return v

    @field_validator("economic_code")
    @classmethod
    def _economic(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{10,14}", v):
            raise ValueError("کد اقتصادی ۱۰ تا ۱۴ رقم است")
        return v

    @model_validator(mode="after")
    def _credit(self) -> PartyFields:
        if self.credit_unlimited and self.credit_limit is not None:
            raise ValueError("اعتبار نامحدود سقف ندارد؛ یا سقف بگذارید یا نامحدود")
        return self

    @model_validator(mode="after")
    def _identity(self) -> PartyFields:
        if not (self.is_customer or self.is_supplier):
            raise ValueError("طرف‌حساب باید مشتری، تأمین‌کننده یا هر دو باشد")
        n = self.national_id
        if n is not None:
            if self.party_type == "person" and not valid_national_code(n):
                raise ValueError("کد ملی نامعتبر است")
            # The legal-entity ID checksum is not verified here, only its form.
            if self.party_type == "company" and not re.fullmatch(r"\d{11}", n):
                raise ValueError("شناسه ملی اشخاص حقوقی ۱۱ رقم است")
        return self


class PartyCreateIn(PartyFields):
    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9-]+$")


class PartyUpdateIn(PartyFields):
    is_active: bool = True


class PartyOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    party_type: PartyType
    is_customer: bool
    is_supplier: bool
    group_id: uuid.UUID | None
    group_name: str | None
    national_id: str | None
    economic_code: str | None
    registration_no: str | None
    phone: str | None
    mobile: str | None
    email: str | None
    postal_code: str | None
    city: str | None
    address: str | None
    payment_terms_days: int | None
    credit_limit: Money | None
    credit_unlimited: bool
    balance: Money
    is_active: bool
    # Identity and contact fields are masked for users without parties.manage.
    masked: bool
    created_at: datetime
    row_version: str


class PartySummary(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    party_type: PartyType
    is_customer: bool
    is_supplier: bool
    group_name: str | None
    mobile: str | None
    credit_limit: Money | None
    credit_unlimited: bool
    balance: Money
    is_active: bool


class PartyQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    q: str | None = Field(default=None, max_length=100)
    role: Literal["customer", "supplier"] | None = None
    group_id: uuid.UUID | None = None
    active: bool | None = None
    # Only parties that owe us (receivable) or that we owe (payable).
    balance: Literal["debtor", "creditor"] | None = None


class StatementLine(BaseModel):
    voucher_id: uuid.UUID
    voucher_number: int | None
    document_date: date
    description: str | None
    account_code: str
    account_name: str
    debit: Money
    credit: Money
    balance: Money


class StatementOut(BaseModel):
    party_id: uuid.UUID
    party_name: str
    date_from: date | None
    date_to: date | None
    opening_balance: Money
    total_debit: Money
    total_credit: Money
    closing_balance: Money
    lines: list[StatementLine]


class NoteIn(_In):
    body: str = Field(min_length=2, max_length=1000)
    follow_up_on: date | None = None


class NoteOut(BaseModel):
    id: uuid.UUID
    party_id: uuid.UUID
    party_name: str
    body: str
    follow_up_on: date | None
    done: bool
    author: str
    created_at: datetime


class GroupIn(_In):
    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=2, max_length=100)


class GroupOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
