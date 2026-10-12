from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.excel import RowError
from app.core.money import _FA, Money

Method = Literal["cash", "bank", "cheque"]
Against = Literal["receivable", "payable"]
DocKind = Literal["receipt", "payment", "transfer", "settlement"]
ChequeAction = Literal["deposit", "clear", "bounce", "return", "redeposit", "cancel"]


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


def _digits(v: str | None) -> str | None:
    if v is None:
        return None
    s = re.sub(r"[\s\-]", "", v.translate(_FA)).upper()
    return s or None


# --- money accounts ---------------------------------------------------------


class AccountFields(_In):
    name: str = Field(min_length=2, max_length=150)
    branch_id: uuid.UUID | None = None
    bank_name: str | None = Field(default=None, max_length=100)
    bank_branch: str | None = Field(default=None, max_length=100)
    account_no: str | None = Field(default=None, max_length=30)
    iban: str | None = Field(default=None, max_length=34)

    @field_validator("account_no", "iban")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _digits(v)

    @field_validator("iban")
    @classmethod
    def _iban(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith("IR"):
            v = "IR" + v
        if not re.fullmatch(r"IR\d{24}", v):
            raise ValueError("شماره شبا باید IR و ۲۴ رقم باشد")
        # ISO 13616 mod-97 check.
        rearranged = v[4:] + "1827" + v[2:4]
        if int(rearranged) % 97 != 1:
            raise ValueError("شماره شبا نامعتبر است")
        return v


class AccountCreateIn(AccountFields):
    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9-]+$")
    kind: Literal["cash", "bank"]

    @model_validator(mode="after")
    def _branch(self) -> AccountCreateIn:
        if self.kind == "cash" and self.branch_id is None:
            raise ValueError("صندوق باید به یک شعبه تعلق داشته باشد")
        return self


class AccountUpdateIn(AccountFields):
    is_active: bool = True


class AccountOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    branch_id: uuid.UUID | None
    branch_name: str | None
    bank_name: str | None
    bank_branch: str | None
    account_no: str | None
    iban: str | None
    is_active: bool
    # Final vouchers only.
    balance: Money
    row_version: str


# --- documents --------------------------------------------------------------


class ChequeIn(_In):
    number: str = Field(min_length=1, max_length=30)
    sayad_id: str | None = Field(default=None, max_length=20)
    bank_name: str | None = Field(default=None, max_length=100)
    drawer: str | None = Field(default=None, max_length=150)
    due_date: date

    @field_validator("number", "sayad_id")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _digits(v)

    @field_validator("sayad_id")
    @classmethod
    def _sayad(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{16}", v):
            raise ValueError("شناسه صیادی ۱۶ رقم است")
        return v


class LineIn(_In):
    method: Method
    # cash/bank: the box or account. Issued cheque: the account it is drawn on.
    money_account_id: uuid.UUID | None = None
    amount: Money = Field(gt=0)
    reference: str | None = Field(default=None, max_length=60)
    cheque: ChequeIn | None = None

    @model_validator(mode="after")
    def _instrument(self) -> LineIn:
        if self.method == "cheque" and self.cheque is None:
            raise ValueError("مشخصات چک را وارد کنید")
        if self.method != "cheque" and self.cheque is not None:
            raise ValueError("مشخصات چک فقط برای روش چک")
        if self.method != "cheque" and self.money_account_id is None:
            raise ValueError("صندوق یا حساب بانکی را انتخاب کنید")
        return self


class ReceiptIn(_In):
    branch_id: uuid.UUID
    document_date: date
    party_id: uuid.UUID
    # Empty = receivable for customers, payable for supplier-only parties.
    against: Against | None = None
    description: str | None = Field(default=None, max_length=500)
    lines: list[LineIn] = Field(min_length=1, max_length=50)


class TransferIn(_In):
    branch_id: uuid.UUID
    document_date: date
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Money = Field(gt=0)
    reference: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _distinct(self) -> TransferIn:
        if self.from_account_id == self.to_account_id:
            raise ValueError("مبدأ و مقصد انتقال یکی است")
        return self


class SettlementIn(_In):
    """Card-reader settlement: the bank deposits ``amount − fee`` of card sales."""

    branch_id: uuid.UUID
    document_date: date
    bank_account_id: uuid.UUID
    amount: Money = Field(gt=0)
    fee: Money = Field(default=Decimal(0), ge=0)
    reference: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _fee(self) -> SettlementIn:
        if self.fee >= self.amount:
            raise ValueError("کارمزد باید کمتر از مبلغ تسویه باشد")
        return self


class ReverseIn(_In):
    reason: str = Field(min_length=2, max_length=500)
    # Empty = the original document date.
    document_date: date | None = None


class LineOut(BaseModel):
    line_no: int
    method: str
    money_account_id: uuid.UUID | None
    money_account_name: str | None
    amount: Money
    reference: str | None
    cheque_id: uuid.UUID | None
    cheque_number: str | None
    cheque_due_date: date | None
    cheque_status: str | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    number: int | None
    branch_id: uuid.UUID
    document_date: date
    party_id: uuid.UUID | None
    party_name: str | None
    against: str | None
    from_account_id: uuid.UUID | None
    from_account_name: str | None
    to_account_id: uuid.UUID | None
    to_account_name: str | None
    amount: Money
    fee: Money
    reference: str | None
    description: str | None
    voucher_id: uuid.UUID | None
    reversal_voucher_id: uuid.UUID | None
    reversed_at: datetime | None
    reversal_reason: str | None
    lines: list[LineOut]
    created_at: datetime
    row_version: str


class DocumentSummary(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    number: int | None
    document_date: date
    party_name: str | None
    amount: Money
    description: str | None


class DocumentQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    kind: DocKind | None = None
    status: Literal["final", "reversed"] | None = None
    party_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


# --- cheques ----------------------------------------------------------------


class ChequeEventOut(BaseModel):
    seq: int
    event_date: date
    from_status: str | None
    to_status: str
    money_account_name: str | None
    voucher_id: uuid.UUID | None
    note: str | None
    user: str | None
    created_at: datetime


class ChequeOut(BaseModel):
    id: uuid.UUID
    direction: str
    status: str
    party_id: uuid.UUID
    party_name: str
    number: str
    sayad_id: str | None
    bank_name: str | None
    drawer: str | None
    amount: Money
    due_date: date
    money_account_id: uuid.UUID | None
    money_account_name: str | None
    document_id: uuid.UUID
    document_number: int | None
    actions: list[str]
    events: list[ChequeEventOut]
    row_version: str


class ChequeSummary(BaseModel):
    id: uuid.UUID
    direction: str
    status: str
    party_name: str
    number: str
    bank_name: str | None
    amount: Money
    due_date: date
    overdue: bool


class ChequeQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    direction: Literal["received", "issued"] | None = None
    status: str | None = Field(default=None, max_length=10)
    # Open cheques (in hand, deposited, issued) due on or before this date.
    due_until: date | None = None
    party_id: uuid.UUID | None = None


class ChequeActionIn(_In):
    action: ChequeAction
    event_date: date
    # deposit / clear of a received cheque: the bank account.
    money_account_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=300)


# --- bank statements --------------------------------------------------------


class StatementLineOut(BaseModel):
    id: uuid.UUID
    line_date: date
    amount: Money
    description: str | None
    reference: str | None
    balance: Money | None
    voucher_line_id: uuid.UUID | None
    voucher_id: uuid.UUID | None
    voucher_number: int | None
    matched_at: datetime | None


class StatementQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=500)
    matched: bool | None = None
    date_from: date | None = None
    date_to: date | None = None


class BookLineOut(BaseModel):
    voucher_line_id: uuid.UUID
    voucher_id: uuid.UUID
    voucher_number: int | None
    document_date: date
    description: str | None
    # Positive = into the account.
    amount: Money


class MatchIn(_In):
    voucher_line_id: uuid.UUID


class AutoMatchOut(BaseModel):
    matched: int
    ambiguous: int
    unmatched: int


class ReconciliationOut(BaseModel):
    account_id: uuid.UUID
    as_of: date
    book_balance: Money
    # The bank's own running balance on the last statement line up to ``as_of``.
    statement_balance: Money | None
    statement_unmatched: list[StatementLineOut]
    book_unmatched: list[BookLineOut]
    # book − Σ(unmatched book lines) + Σ(unmatched statement lines); equals the
    # statement balance when every difference is explained.
    adjusted_book_balance: Money


class StatementImportOut(BaseModel):
    total_rows: int
    new_rows: int
    # Already imported (same date, amount, reference, description and balance): skipped.
    duplicate_rows: int
    errors: list[RowError]
    sample: list[dict[str, Any]]
