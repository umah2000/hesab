"""Helpers shared by the reports: scoping, ranges, value formatting, paging."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.core.errors import DomainError, NotFoundError
from app.modules.iam.guard import Actor
from app.modules.inventory.services.stock import tehran_today
from app.modules.reports.schemas import ALL_TIME_START

ZERO = Decimal(0)
MAX_DAYS = 366


def branches(actor: Actor, branch_id: uuid.UUID | None) -> set[uuid.UUID] | None:
    """Branches a report may read: the requested one (if allowed) or the actor's scope."""
    if branch_id is not None:
        if not actor.can_access_branch(branch_id):
            raise NotFoundError("شعبه یافت نشد")
        return {branch_id}
    if actor.branch_ids is None:
        return None
    return set(actor.branch_ids) or {uuid.UUID(int=0)}


def date_range(d_from: date | None, d_to: date | None, default_days: int = 30) -> tuple[date, date]:
    end = d_to or tehran_today()
    start = d_from or end - timedelta(days=default_days - 1)
    if start > end:
        raise DomainError("تاریخ شروع بعد از تاریخ پایان است", code="invalid_range")
    if start > ALL_TIME_START and (end - start).days >= MAX_DAYS:
        raise DomainError("بازه گزارش حداکثر یک سال است", code="range_too_long")
    return start, end


def m(v: Decimal | None) -> str:
    return format((v or ZERO).quantize(Decimal("0.0001")), "f")


def q(v: Decimal | None) -> str:
    return format((v or ZERO).quantize(Decimal("0.001")), "f")


def pct(part: Decimal, whole: Decimal) -> str | None:
    if not whole:
        return None
    return format((part * 100 / whole).quantize(Decimal("0.01")), "f")


def page(rows: list[dict[str, Any]], page_no: int, size: int) -> list[dict[str, Any]]:
    start = (page_no - 1) * size
    return rows[start : start + size]


def day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """UTC instants of [start 00:00, end+1 00:00) in the shop's time zone (Tehran)."""
    tz = ZoneInfo("Asia/Tehran")
    lo = datetime.combine(start, time.min, tz).astimezone(UTC)
    hi = datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(UTC)
    return lo, hi
