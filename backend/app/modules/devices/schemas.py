from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Transport = Literal["none", "tcp", "windows", "serial"]


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class DeviceConfigIn(_In):
    name: str = Field(min_length=2, max_length=100)
    printer_transport: Transport = "none"
    printer_address: str | None = Field(default=None, max_length=120)
    paper_width: Literal[58, 80] = 80
    cut_paper: bool = True
    drawer_enabled: bool = False
    drawer_pin: Literal[2, 5] = 2

    @model_validator(mode="after")
    def _address(self) -> DeviceConfigIn:
        a = self.printer_address
        if self.printer_transport == "none":
            self.printer_address = None
            if self.drawer_enabled:
                raise ValueError("کشوی پول از طریق چاپگر فیش باز می‌شود؛ ابتدا چاپگر را تنظیم کنید")
            return self
        if not a:
            raise ValueError("نشانی چاپگر را وارد کنید")
        if self.printer_transport == "tcp" and not re.fullmatch(
            r"[A-Za-z0-9.\-]{1,100}(:\d{1,5})?", a
        ):
            raise ValueError("نشانی شبکه چاپگر باید مثل 192.168.1.50:9100 باشد")
        if self.printer_transport == "serial" and not re.fullmatch(
            r"(COM\d{1,3}|/dev/[A-Za-z0-9/_\-]+)(:\d{3,6})?", a
        ):
            raise ValueError("درگاه سریال باید مثل COM3:9600 باشد")
        return self


class DeviceCreateIn(DeviceConfigIn):
    branch_id: uuid.UUID
    cash_register_id: uuid.UUID | None = None


class DeviceOut(BaseModel):
    id: uuid.UUID
    name: str
    branch_id: uuid.UUID
    cash_register_id: uuid.UUID | None
    cash_register_name: str | None
    status: str
    online: bool
    last_seen_at: datetime | None
    paired_at: datetime | None
    agent_version: str | None
    platform: str | None
    printer_state: str | None
    printer_transport: str
    printer_address: str | None
    paper_width: int
    cut_paper: bool
    drawer_enabled: bool
    drawer_pin: int
    # Only in the response that creates it; shown once to type into the agent.
    pairing_code: str | None = None
    pairing_expires_at: datetime | None
    row_version: str


class PairIn(_In):
    code: str = Field(min_length=4, max_length=20)
    agent_version: str = Field(max_length=20)
    platform: str | None = Field(default=None, max_length=100)


class PairOut(BaseModel):
    device_id: uuid.UUID
    name: str
    # Shown once; the agent stores it locally (Windows DPAPI / file readable by the service).
    token: str


class PrinterConfig(BaseModel):
    transport: str
    address: str | None
    paper_width: int
    cut_paper: bool
    drawer_enabled: bool
    drawer_pin: int


class AgentJob(BaseModel):
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]


class PollIn(_In):
    agent_version: str | None = Field(default=None, max_length=20)
    printer_state: str | None = Field(default=None, max_length=200)


class PollOut(BaseModel):
    name: str
    printer: PrinterConfig
    job: AgentJob | None


class JobResultIn(_In):
    status: Literal["done", "failed"]
    error: str | None = Field(default=None, max_length=300)


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    error: str | None
    attempts: int
    created_at: datetime
    sent_at: datetime | None
    finished_at: datetime | None


class RegisterDeviceOut(BaseModel):
    """What the POS needs: may it print through an agent, and open the drawer?"""

    device_id: uuid.UUID | None
    online: bool
    printer: bool
    drawer: bool


class PrintReceiptIn(_In):
    invoice_id: uuid.UUID
    reprint: bool = False
    # False: no paper (automatic printing is off) — only the drawer of a cash sale opens.
    paper: bool = True


class DrawerIn(_In):
    cash_register_id: uuid.UUID
    reason: str = Field(min_length=2, max_length=200)
