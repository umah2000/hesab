"""Device Agents: registration, pairing, job queue and print requests (ADR-0015)."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from nextcam_core import receipt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.security import hash_token, new_token
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.devices.models import Device, DeviceJob
from app.modules.devices.schemas import (
    AgentJob,
    DeviceConfigIn,
    DeviceCreateIn,
    DeviceOut,
    DrawerIn,
    JobOut,
    JobResultIn,
    PairIn,
    PairOut,
    PollIn,
    PollOut,
    PrinterConfig,
    PrintReceiptIn,
    RegisterDeviceOut,
)
from app.modules.iam.guard import Actor, NotAuthenticatedError
from app.modules.organization.models import Branch, CashRegister, Organization
from app.modules.sales.services.invoices import get_invoice

PAIRING_TTL = timedelta(minutes=15)
# The agent polls about once a second; a minute of silence means it is gone.
ONLINE_WITHIN = timedelta(seconds=15)
SEEN_EVERY = timedelta(seconds=5)
# A receipt that could not be printed promptly is never printed later by surprise.
JOB_TTL = timedelta(seconds=120)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _norm_code(code: str) -> str:
    return code.upper().replace("-", "").replace(" ", "")


def _new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def online(d: Device, now: datetime | None = None) -> bool:
    seen = _aware(d.last_seen_at)
    return d.status == "active" and seen is not None and (now or utcnow()) - seen <= ONLINE_WITHIN


def device_out(s: Session, d: Device, code: str | None = None) -> DeviceOut:
    reg = s.get(CashRegister, d.cash_register_id) if d.cash_register_id else None
    return DeviceOut(
        id=d.id,
        name=d.name,
        branch_id=d.branch_id,
        cash_register_id=d.cash_register_id,
        cash_register_name=reg.name if reg else None,
        status=d.status,
        online=online(d),
        last_seen_at=d.last_seen_at,
        paired_at=d.paired_at,
        agent_version=d.agent_version,
        platform=d.platform,
        printer_state=d.printer_state,
        printer_transport=d.printer_transport,
        printer_address=d.printer_address,
        paper_width=d.paper_width,
        cut_paper=d.cut_paper,
        drawer_enabled=d.drawer_enabled,
        drawer_pin=d.drawer_pin,
        pairing_code=code,
        pairing_expires_at=d.pairing_expires_at if d.pairing_code_hash else None,
        row_version=version_to_str(d.row_version),
    )


def _apply(d: Device, data: DeviceConfigIn) -> None:
    d.name = data.name
    d.printer_transport, d.printer_address = data.printer_transport, data.printer_address
    d.paper_width, d.cut_paper = data.paper_width, data.cut_paper
    d.drawer_enabled, d.drawer_pin = data.drawer_enabled, data.drawer_pin


def _set_code(d: Device) -> str:
    code = _new_code()
    d.pairing_code_hash = hash_token(_norm_code(code))
    d.pairing_expires_at = utcnow() + PAIRING_TTL
    return code


# --- administration ----------------------------------------------------------


def create(s: Session, actor: Actor, data: DeviceCreateIn) -> DeviceOut:
    branch = s.get(Branch, data.branch_id)
    if branch is None or not actor.can_access_branch(branch.id):
        raise NotFoundError("شعبه یافت نشد")
    if data.cash_register_id is not None:
        reg = s.get(CashRegister, data.cash_register_id)
        if reg is None or reg.branch_id != branch.id:
            raise DomainError("صندوق در این شعبه یافت نشد", code="bad_register")
    d = Device(
        branch_id=branch.id,
        cash_register_id=data.cash_register_id,
        status="pending",
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    _apply(d, data)
    code = _set_code(d)
    s.add(d)
    try:
        s.flush()
    except IntegrityError as e:
        raise ConflictError("این صندوق از قبل دستگاه فعال دارد", code="register_has_device") from e
    audit.record(
        s,
        "devices.created",
        user_id=actor.user_id,
        branch_id=d.branch_id,
        entity_type="device",
        entity_id=d.id,
        data={"name": d.name},
    )
    s.refresh(d)
    return device_out(s, d, code)


def _get(s: Session, actor: Actor, device_id: uuid.UUID, lock: bool = False) -> Device:
    d = s.get(Device, device_id, with_for_update=lock)
    if d is None or not actor.can_access_branch(d.branch_id):
        raise NotFoundError("دستگاه یافت نشد")
    return d


def get(s: Session, actor: Actor, device_id: uuid.UUID) -> DeviceOut:
    return device_out(s, _get(s, actor, device_id))


def list_devices(s: Session, actor: Actor) -> list[DeviceOut]:
    rows = list(s.scalars(select(Device).order_by(Device.status, Device.name)))
    return [device_out(s, d) for d in rows if actor.can_access_branch(d.branch_id)]


def update(
    s: Session, actor: Actor, device_id: uuid.UUID, data: DeviceConfigIn, version: str
) -> DeviceOut:
    d = _get(s, actor, device_id, lock=True)
    check_version(d.row_version, version, "این دستگاه")
    if d.status == "revoked":
        raise DomainError("دستگاه باطل‌شده تغییر نمی‌کند", code="device_revoked")
    _apply(d, data)
    d.updated_by = actor.user_id
    s.flush()
    audit.record(
        s,
        "devices.configured",
        user_id=actor.user_id,
        branch_id=d.branch_id,
        entity_type="device",
        entity_id=d.id,
        data=data.model_dump(mode="json"),
    )
    s.refresh(d)
    return device_out(s, d)


def new_pairing_code(s: Session, actor: Actor, device_id: uuid.UUID, version: str) -> DeviceOut:
    """A fresh code; the current agent keeps working until a new one pairs (then it stops)."""
    d = _get(s, actor, device_id, lock=True)
    check_version(d.row_version, version, "این دستگاه")
    if d.status == "revoked":
        raise DomainError("دستگاه باطل‌شده است؛ دستگاه تازه تعریف کنید", code="device_revoked")
    code = _set_code(d)
    d.updated_by = actor.user_id
    s.flush()
    audit.record(
        s,
        "devices.pairing_code",
        user_id=actor.user_id,
        branch_id=d.branch_id,
        entity_type="device",
        entity_id=d.id,
    )
    s.refresh(d)
    return device_out(s, d, code)


def revoke(s: Session, actor: Actor, device_id: uuid.UUID, version: str) -> DeviceOut:
    d = _get(s, actor, device_id, lock=True)
    check_version(d.row_version, version, "این دستگاه")
    d.status, d.token_hash = "revoked", None
    d.pairing_code_hash = d.pairing_expires_at = None
    d.updated_by = actor.user_id
    for j in list(
        s.scalars(
            select(DeviceJob).where(
                DeviceJob.device_id == d.id, DeviceJob.status.in_(("queued", "sent"))
            )
        )
    ):
        j.status, j.error, j.finished_at = "expired", "دستگاه باطل شد", utcnow()
    s.flush()
    audit.record(
        s,
        "devices.revoked",
        user_id=actor.user_id,
        branch_id=d.branch_id,
        entity_type="device",
        entity_id=d.id,
    )
    s.refresh(d)
    return device_out(s, d)


def jobs(s: Session, actor: Actor, device_id: uuid.UUID, limit: int = 30) -> list[JobOut]:
    d = _get(s, actor, device_id)
    rows = s.scalars(
        select(DeviceJob)
        .where(DeviceJob.device_id == d.id)
        .order_by(DeviceJob.created_at.desc())
        .limit(limit)
    )
    return [job_out(j) for j in rows]


def job_out(j: DeviceJob) -> JobOut:
    return JobOut(
        id=j.id,
        kind=j.kind,
        status=j.status,
        error=j.error,
        attempts=j.attempts,
        created_at=j.created_at,
        sent_at=j.sent_at,
        finished_at=j.finished_at,
    )


# --- agent side ----------------------------------------------------------------


def pair(s: Session, data: PairIn) -> PairOut:
    h = hash_token(_norm_code(data.code))
    d = s.scalar(select(Device).where(Device.pairing_code_hash == h).with_for_update())
    expires = _aware(d.pairing_expires_at) if d else None
    if d is None or d.status == "revoked" or expires is None or expires < utcnow():
        raise NotAuthenticatedError("کد جفت‌سازی نامعتبر یا منقضی است")
    token = new_token()
    d.token_hash, d.status, d.paired_at = hash_token(token), "active", utcnow()
    d.pairing_code_hash = d.pairing_expires_at = None
    d.agent_version, d.platform = data.agent_version, data.platform
    s.flush()
    audit.record(
        s,
        "devices.paired",
        user_id=None,
        branch_id=d.branch_id,
        entity_type="device",
        entity_id=d.id,
        data={"agent_version": data.agent_version, "platform": data.platform},
    )
    return PairOut(device_id=d.id, name=d.name, token=token)


def authenticate(s: Session, token: str | None) -> Device:
    if not token:
        raise NotAuthenticatedError("توکن دستگاه لازم است")
    d = s.scalar(select(Device).where(Device.token_hash == hash_token(token)))
    if d is None or d.status != "active":
        raise NotAuthenticatedError("توکن دستگاه نامعتبر است")
    return d


def _printer(d: Device) -> PrinterConfig:
    return PrinterConfig(
        transport=d.printer_transport,
        address=d.printer_address,
        paper_width=d.paper_width,
        cut_paper=d.cut_paper,
        drawer_enabled=d.drawer_enabled,
        drawer_pin=d.drawer_pin,
    )


def poll(s: Session, d: Device, data: PollIn) -> PollOut:
    now = utcnow()
    seen = _aware(d.last_seen_at)
    if (
        seen is None
        or now - seen >= SEEN_EVERY
        or data.printer_state != d.printer_state
        or (data.agent_version and data.agent_version != d.agent_version)
    ):
        d.last_seen_at, d.printer_state = now, data.printer_state
        if data.agent_version:
            d.agent_version = data.agent_version
    # Stale work is dropped, never printed late; a sent job with no answer is reported.
    for j in list(
        s.scalars(
            select(DeviceJob).where(
                DeviceJob.device_id == d.id,
                DeviceJob.status.in_(("queued", "sent")),
                DeviceJob.created_at < now - JOB_TTL,
            )
        )
    ):
        j.error = (
            "دستگاه در زمان مقرر در دسترس نبود"
            if j.status == "queued"
            else "پاسخی از دستگاه نرسید؛ نتیجه چاپ را روی کاغذ بررسی کنید"
        )
        j.status, j.finished_at = "expired", now
    job = s.scalar(
        select(DeviceJob)
        .where(DeviceJob.device_id == d.id, DeviceJob.status == "queued")
        .order_by(DeviceJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    out = None
    if job is not None:
        job.status, job.sent_at, job.attempts = "sent", now, job.attempts + 1
        out = AgentJob(id=job.id, kind=job.kind, payload=json.loads(job.payload))
    s.flush()
    return PollOut(name=d.name, printer=_printer(d), job=out)


def report(s: Session, d: Device, job_id: uuid.UUID, data: JobResultIn) -> JobOut:
    j = s.get(DeviceJob, job_id, with_for_update=True)
    if j is None or j.device_id != d.id:
        raise NotFoundError("کار یافت نشد")
    if j.status != "sent":
        raise ConflictError("نتیجه این کار قبلاً ثبت شده یا منقضی است", code="job_closed")
    j.status, j.finished_at = data.status, utcnow()
    j.error = data.error if data.status == "failed" else None
    d.last_seen_at = utcnow()
    s.flush()
    return job_out(j)


# --- requests from the POS -----------------------------------------------------


def _register_device(s: Session, register_id: uuid.UUID) -> Device | None:
    return s.scalar(
        select(Device).where(Device.cash_register_id == register_id, Device.status == "active")
    )


def for_register(s: Session, actor: Actor, register_id: uuid.UUID) -> RegisterDeviceOut:
    reg = s.get(CashRegister, register_id)
    if reg is None or not actor.can_access_branch(reg.branch_id):
        raise NotFoundError("صندوق یافت نشد")
    d = _register_device(s, reg.id)
    if d is None:
        return RegisterDeviceOut(device_id=None, online=False, printer=False, drawer=False)
    return RegisterDeviceOut(
        device_id=d.id,
        online=online(d),
        printer=d.printer_transport != "none",
        drawer=d.drawer_enabled,
    )


def _enqueue(
    s: Session,
    actor: Actor,
    d: Device,
    kind: str,
    payload: dict[str, Any],
    source: uuid.UUID | None,
) -> DeviceJob:
    j = DeviceJob(
        device_id=d.id,
        kind=kind,
        status="queued",
        payload=json.dumps(payload, ensure_ascii=False),
        source_id=source,
        created_by=actor.user_id,
    )
    s.add(j)
    s.flush()
    return j


def _printing_device(s: Session, register_id: uuid.UUID) -> Device:
    d = _register_device(s, register_id)
    if d is None or d.printer_transport == "none":
        raise DomainError(
            "برای این صندوق چاپگر فیش از طریق Device Agent تنظیم نشده است", code="no_device"
        )
    if not online(d):
        raise DomainError(
            f"Device Agent «{d.name}» در دسترس نیست؛ از چاپ مرورگر استفاده کنید",
            code="device_offline",
        )
    return d


def print_receipt(s: Session, actor: Actor, data: PrintReceiptIn) -> JobOut:
    inv = get_invoice(s, actor, data.invoice_id)
    if inv.status != "final":
        raise DomainError("فقط فاکتور قطعی چاپ می‌شود", code="not_final")
    d = _printing_device(s, inv.cash_register_id)
    prior = list(s.scalars(select(DeviceJob.kind).where(DeviceJob.source_id == inv.id)))
    reprint = data.reprint or "receipt" in prior
    has_cash = any(p.method == "cash" and p.amount > 0 for p in inv.payments)
    # The drawer opens once per cash sale or cash refund: with its first job only.
    open_drawer = d.drawer_enabled and has_cash and not prior and not data.reprint
    if not data.paper:
        if not open_drawer:
            raise DomainError("کشوی پول برای این فاکتور باز نمی‌شود", code="no_drawer")
        return job_out(_enqueue(s, actor, d, "drawer", {"pin": d.drawer_pin}, inv.id))
    org = s.scalars(select(Organization)).one()
    payload = receipt.build(
        inv,
        organization=org.name,
        header=org.receipt_header,
        footer=org.receipt_footer,
        currency=org.display_currency,
        timezone=org.timezone,
        reprint=reprint,
        open_drawer=open_drawer,
        cut=d.cut_paper,
    )
    j = _enqueue(s, actor, d, "receipt", payload, inv.id)
    if reprint:
        audit.record(
            s,
            "devices.receipt_reprinted",
            user_id=actor.user_id,
            branch_id=inv.branch_id,
            entity_type="sales_invoice",
            entity_id=inv.id,
            data={"number": inv.number},
        )
    return job_out(j)


def open_drawer(s: Session, actor: Actor, data: DrawerIn) -> JobOut:
    reg = s.get(CashRegister, data.cash_register_id)
    if reg is None or not actor.can_access_branch(reg.branch_id):
        raise NotFoundError("صندوق یافت نشد")
    d = _printing_device(s, reg.id)
    if not d.drawer_enabled:
        raise DomainError("کشوی پول برای این صندوق فعال نیست", code="no_drawer")
    j = _enqueue(s, actor, d, "drawer", {"pin": d.drawer_pin}, None)
    audit.record(
        s,
        "devices.drawer_opened",
        user_id=actor.user_id,
        branch_id=reg.branch_id,
        entity_type="cash_register",
        entity_id=reg.id,
        data={"reason": data.reason},
    )
    return job_out(j)


def test_print(s: Session, actor: Actor, device_id: uuid.UUID) -> JobOut:
    d = _get(s, actor, device_id)
    if d.status != "active" or d.printer_transport == "none":
        raise DomainError("دستگاه جفت نشده یا چاپگر ندارد", code="no_device")
    return job_out(_enqueue(s, actor, d, "test", receipt.test_page(d.name, d.paper_width), None))


def job_status(s: Session, actor: Actor, job_id: uuid.UUID) -> JobOut:
    j = s.get(DeviceJob, job_id)
    d = s.get(Device, j.device_id) if j else None
    if j is None or d is None or not actor.can_access_branch(d.branch_id):
        raise NotFoundError("کار یافت نشد")
    return job_out(j)
