from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.http import PageQuery
from app.core.money import Money

DocStatus = Literal["posted", "held", "voided", "reversed"]


class DocumentQuery(PageQuery):
    status: DocStatus | None = None


class IntegrationDocumentOut(BaseModel):
    id: uuid.UUID
    number: str
    kind: Literal["haulage", "sales"] | None
    counterparty_code: str | None
    counterparty_name: str | None
    document_date: date | None
    total: Money | None
    status: DocStatus
    problem: str | None
    void_reason: str | None
    voucher_id: uuid.UUID | None
    voucher_number: int | None
    reversal_voucher_id: uuid.UUID | None
    reversal_voucher_number: int | None
    created_at: datetime
    updated_at: datetime


class IntegrationEventOut(BaseModel):
    event_type: str
    result: str
    message: str | None
    received_at: datetime
    document_number: str | None


class IntegrationStatusOut(BaseModel):
    """Whether the connection is configured, and how much is waiting for the accountant."""

    configured: bool
    held: int
    posted: int
    last_event_at: datetime | None
    last_events: list[IntegrationEventOut] = Field(default_factory=list)
