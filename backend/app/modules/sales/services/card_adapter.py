"""What a card-reader driver offers the payment state machine (terminal.py)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class AdapterResult:
    status: str
    rrn: str | None = None
    trace_no: str | None = None
    masked_pan: str | None = None
    response_code: str | None = None


class PaymentTerminalAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property
    def verified(self) -> bool: ...
    @property
    def simulated(self) -> bool: ...
    @property
    def scenarios(self) -> tuple[str, ...]: ...
    # True when start_sale waits for the customer: it then runs after the response.
    @property
    def background(self) -> bool: ...
    @property
    def can_cancel(self) -> bool: ...

    def prepare(self) -> str | None:
        """The provider's id for a new attempt, before anything is sent to the device."""
        ...

    def start_sale(
        self, request_id: uuid.UUID, provider_ref: str | None, amount: Decimal, scenario: str | None
    ) -> AdapterResult: ...

    def inquire(
        self,
        request_id: uuid.UUID,
        provider_ref: str | None,
        amount: Decimal,
        response_code: str | None,
        cancel: bool = False,
    ) -> AdapterResult: ...
