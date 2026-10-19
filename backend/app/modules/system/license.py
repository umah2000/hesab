"""License and activation (phase 10, ADR-0021).

An offline license is a payload signed by the vendor (Ed25519) for one installation
(the organization id, which survives backup and restore). It sets limits on *adding*
branches, registers and users and on optional features. It never stops what already
runs: sales, sign-in, reports and backups work with no license, an expired one or one
that no longer verifies — those only show warnings to managers.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import date
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import DomainError
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.organization.models import Branch, CashRegister, Organization
from app.modules.system import license_keys
from app.modules.system.models import License

PREFIX = "NCL1"
REQUEST_PREFIX = "NCR1"
WARN_DAYS = 30
Kind = Literal["branches", "registers", "users"]
KIND_LABEL = {"branches": "شعبه", "registers": "صندوق", "users": "کاربر فعال"}
FEATURE_LABEL = {"distribution": "اپلیکیشن ویزیتور و پخش"}


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branches: int | None = Field(default=None, ge=1)
    registers: int | None = Field(default=None, ge=1)
    users: int | None = Field(default=None, ge=1)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1]
    kid: str
    license_id: uuid.UUID
    installation_id: uuid.UUID
    customer: str = Field(max_length=200)
    issued_at: date
    valid_until: date | None
    support_until: date | None
    limits: Limits
    features: list[str]
    note: str | None = None


class LicenseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=10, max_length=20_000)


class FeatureOut(BaseModel):
    code: str
    label: str
    enabled: bool


class LimitOut(BaseModel):
    kind: Kind
    label: str
    used: int
    limit: int | None


class LicenseStatus(BaseModel):
    state: Literal["unlicensed", "invalid", "valid", "expiring", "expired"]
    customer: str | None
    license_id: uuid.UUID | None
    issued_at: date | None
    valid_until: date | None
    support_until: date | None
    days_left: int | None
    features: list[FeatureOut]
    limits: list[LimitOut]
    installation_id: uuid.UUID
    request_code: str
    warnings: list[str]


class LicenseError(DomainError):
    code = "license_invalid"


def _today() -> date:
    from zoneinfo import ZoneInfo

    return utcnow().astimezone(ZoneInfo("Asia/Tehran")).date()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def parse(text: str) -> Payload:
    """Verify the signature against the trusted keys, then read the payload."""
    parts = "".join(text.split()).split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("متن وارد‌شده مجوز NEXTCAM نیست")
    try:
        body, sig = _b64d(parts[1]), _b64d(parts[2])
        kid = json.loads(body).get("kid")
    except (binascii.Error, ValueError, AttributeError) as e:
        raise LicenseError("متن مجوز ناقص یا آسیب‌دیده است") from e
    public = license_keys.TRUSTED.get(kid) if isinstance(kid, str) else None
    if public is None:
        raise LicenseError("امضای این مجوز از ناشر شناخته‌شده نیست")
    try:
        Ed25519PublicKey.from_public_bytes(_b64d(public)).verify(sig, body)
    except (InvalidSignature, ValueError) as e:
        raise LicenseError("امضای مجوز معتبر نیست") from e
    try:
        return Payload.model_validate_json(body)
    except ValidationError as e:
        raise LicenseError("محتوای مجوز با این نسخه از برنامه سازگار نیست") from e


def _org(s: Session) -> Organization:
    org: Organization | None = s.scalar(select(Organization))
    if org is None:
        raise DomainError("سازمان هنوز راه‌اندازی نشده است", code="no_organization")
    return org


def request_code(s: Session) -> str:
    org = _org(s)
    data = {"installation_id": str(org.id), "customer": org.name}
    return f"{REQUEST_PREFIX}.{_b64e(json.dumps(data, ensure_ascii=False).encode())}"


def _active_row(s: Session) -> License | None:
    return s.scalar(
        select(License).where(License.status == "active").order_by(License.created_at.desc())
    )


def active(s: Session) -> Payload | None:
    """The installed license if it still verifies for this installation, else None."""
    row = _active_row(s)
    if row is None:
        return None
    try:
        p = parse(row.text)
    except LicenseError:
        return None
    return p if p.installation_id == _org(s).id else None


def install(s: Session, actor: Actor, text: str) -> LicenseStatus:
    p = parse(text)
    org = _org(s)
    if p.installation_id != org.id:
        raise LicenseError(
            "این مجوز برای نصب دیگری صادر شده است؛ کد درخواست همین نصب را برای فروشنده بفرستید",
            code="license_other_installation",
        )
    current = _active_row(s)
    if current is not None and current.license_id == p.license_id:
        return status(s)
    if s.scalar(select(License.id).where(License.license_id == p.license_id)):
        raise LicenseError("این مجوز قبلاً نصب و جایگزین شده است", code="license_reused")
    if current is not None:
        current.status = "replaced"
    s.add(
        License(
            license_id=p.license_id,
            text="".join(text.split()),
            status="active",
            installed_by=actor.user_id,
        )
    )
    s.flush()
    audit.record(
        s,
        "system.license_installed",
        user_id=actor.user_id,
        entity_type="license",
        entity_id=p.license_id,
        data={
            "customer": p.customer,
            "valid_until": p.valid_until.isoformat() if p.valid_until else None,
            "limits": p.limits.model_dump(),
            "features": p.features,
        },
    )
    return status(s)


def usage(s: Session) -> dict[str, int]:
    def count(model: Any) -> int:
        return (
            s.scalar(select(func.count()).select_from(model).where(model.is_active == true())) or 0
        )

    return {"branches": count(Branch), "registers": count(CashRegister), "users": count(AppUser)}


def status(s: Session) -> LicenseStatus:
    used = usage(s)
    row = _active_row(s)
    p = active(s)
    today = _today()
    warnings: list[str] = []
    days_left = None
    if p is None:
        state = "invalid" if row is not None else "unlicensed"
        warnings.append(
            "مجوز نصب‌شده معتبر نیست؛ با فروشنده تماس بگیرید"
            if row is not None
            else "مجوز نرم‌افزار نصب نشده است"
        )
    else:
        state = "valid"
        if p.valid_until is not None:
            days_left = (p.valid_until - today).days
            if days_left < 0:
                state = "expired"
                warnings.append(
                    "مهلت مجوز نرم‌افزار تمام شده است؛ برای تمدید با فروشنده تماس بگیرید"
                )
            elif days_left <= WARN_DAYS:
                state = "expiring"
                warnings.append(f"مجوز نرم‌افزار تا {days_left} روز دیگر تمام می‌شود")
        for kind, n in used.items():
            limit = getattr(p.limits, kind)
            if limit is not None and n > limit:
                warnings.append(f"تعداد {KIND_LABEL[kind]} ({n}) از سقف مجوز ({limit}) بیشتر است")
    out: dict[str, Any] = {
        "state": state,
        "customer": p.customer if p else None,
        "license_id": p.license_id if p else None,
        "issued_at": p.issued_at if p else None,
        "valid_until": p.valid_until if p else None,
        "support_until": p.support_until if p else None,
        "days_left": days_left,
        "features": [
            {
                "code": f,
                "label": FEATURE_LABEL.get(f, f),
                "enabled": p is not None and f in p.features,
            }
            for f in FEATURE_LABEL
        ],
        "limits": [
            {
                "kind": k,
                "label": KIND_LABEL[k],
                "used": used[k],
                "limit": getattr(p.limits, k) if p else None,
            }
            for k in KIND_LABEL
        ],
        "installation_id": _org(s).id,
        "request_code": request_code(s),
        "warnings": warnings,
    }
    return LicenseStatus.model_validate(out)


def check_limit(s: Session, kind: Kind) -> None:
    """Before adding (or re-activating) one more branch / register / user."""
    p = active(s)
    if p is None:
        return
    limit = getattr(p.limits, kind)
    if limit is not None and usage(s)[kind] >= limit:
        raise DomainError(
            f"سقف «{KIND_LABEL[kind]}» در مجوز نرم‌افزار ({limit}) پر است؛ "
            "برای افزایش با فروشنده تماس بگیرید",
            code="license_limit",
        )


def require_feature(s: Session, feature: str) -> None:
    """Only when a license is installed: unlicensed installations are not restricted."""
    p = active(s)
    if p is not None and feature not in p.features:
        raise DomainError(
            f"امکان «{FEATURE_LABEL.get(feature, feature)}» در مجوز نرم‌افزار نیست",
            code="license_feature",
        )
