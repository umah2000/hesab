"""Fiscal years (Jalali, from 1 Farvardin — Q8) and monthly periods."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import jdatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.accounting.models import FiscalPeriod, FiscalYear
from app.modules.accounting.schemas import FiscalPeriodOut, FiscalYearOut
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor

MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


def jalali_year_range(jy: int) -> tuple[date, date]:
    start = jdatetime.date(jy, 1, 1).togregorian()
    end = jdatetime.date(jy + 1, 1, 1).togregorian() - timedelta(days=1)
    return start, end


def year_out(fy: FiscalYear) -> FiscalYearOut:
    return FiscalYearOut(
        id=fy.id,
        title=fy.title,
        jalali_year=fy.jalali_year,
        start_date=fy.start_date,
        end_date=fy.end_date,
        status=fy.status,  # type: ignore[arg-type]
        closed_at=fy.closed_at,
        row_version=version_to_str(fy.row_version),
        periods=[
            FiscalPeriodOut(
                id=p.id,
                number=p.number,
                title=p.title,
                start_date=p.start_date,
                end_date=p.end_date,
                is_locked=p.is_locked,
                row_version=version_to_str(p.row_version),
            )
            for p in fy.periods
        ],
    )


def list_years(s: Session) -> list[FiscalYearOut]:
    return [
        year_out(fy) for fy in s.scalars(select(FiscalYear).order_by(FiscalYear.start_date.desc()))
    ]


def get_year(s: Session, fy_id: uuid.UUID) -> FiscalYear:
    fy = s.get(FiscalYear, fy_id)
    if fy is None:
        raise NotFoundError("سال مالی یافت نشد")
    return fy


def ensure_year(s: Session, jalali_year: int, actor_id: uuid.UUID | None = None) -> FiscalYear:
    fy = s.scalar(select(FiscalYear).where(FiscalYear.jalali_year == jalali_year))
    if fy is not None:
        return fy
    start, end = jalali_year_range(jalali_year)
    overlap = s.scalar(
        select(FiscalYear.id).where(FiscalYear.start_date <= end, FiscalYear.end_date >= start)
    )
    if overlap:
        raise ConflictError("این سال مالی با سال مالی دیگری هم‌پوشانی دارد", code="year_overlap")
    fy = FiscalYear(
        title=f"سال مالی {jalali_year}",
        jalali_year=jalali_year,
        start_date=start,
        end_date=end,
        status="open",
        created_by=actor_id,
        updated_by=actor_id,
    )
    s.add(fy)
    s.flush()
    for m in range(1, 13):
        p_start = jdatetime.date(jalali_year, m, 1).togregorian()
        p_end = (
            jdatetime.date(jalali_year, m + 1, 1).togregorian() - timedelta(days=1)
            if m < 12
            else end
        )
        s.add(
            FiscalPeriod(
                fiscal_year_id=fy.id,
                number=m,
                title=f"{MONTHS[m - 1]} {jalali_year}",
                start_date=p_start,
                end_date=p_end,
                is_locked=False,
            )
        )
    s.flush()
    s.refresh(fy)
    return fy


def create_year(s: Session, actor: Actor, jalali_year: int) -> FiscalYearOut:
    if s.scalar(select(FiscalYear.id).where(FiscalYear.jalali_year == jalali_year)):
        raise ConflictError("این سال مالی قبلاً تعریف شده است", code="year_exists")
    fy = ensure_year(s, jalali_year, actor.user_id)
    audit.record(
        s,
        "accounting.fiscal_year_created",
        user_id=actor.user_id,
        entity_type="fiscal_year",
        entity_id=fy.id,
        data={"year": jalali_year},
    )
    return year_out(fy)


def current_jalali_year(today: date | None = None) -> int:
    return int(jdatetime.date.fromgregorian(date=today or date.today()).year)


def open_year_for(s: Session, d: date) -> FiscalYear:
    """The open fiscal year containing ``d`` whose period is not locked."""
    fy = s.scalar(select(FiscalYear).where(FiscalYear.start_date <= d, FiscalYear.end_date >= d))
    if fy is None:
        raise DomainError("برای این تاریخ سال مالی تعریف نشده است", code="no_fiscal_year")
    if fy.status != "open":
        raise DomainError("سال مالی این تاریخ بسته شده است", code="fiscal_year_closed")
    period = next((p for p in fy.periods if p.start_date <= d <= p.end_date), None)
    if period is not None and period.is_locked:
        raise DomainError(f"دوره «{period.title}» قفل است", code="period_locked")
    return fy


def set_period_lock(
    s: Session, actor: Actor, period_id: uuid.UUID, locked: bool, version: str
) -> FiscalYearOut:
    p = s.get(FiscalPeriod, period_id)
    if p is None:
        raise NotFoundError("دوره یافت نشد")
    check_version(p.row_version, version, "این دوره")
    if p.fiscal_year.status == "closed" and not locked:
        raise DomainError("دوره‌های سال مالی بسته‌شده قابل بازگشایی نیست", code="fiscal_year_closed")
    p.is_locked = locked
    p.updated_at = utcnow()
    s.flush()
    audit.record(
        s,
        "accounting.period_locked" if locked else "accounting.period_unlocked",
        user_id=actor.user_id,
        entity_type="fiscal_period",
        entity_id=p.id,
        data={"period": p.title},
    )
    s.refresh(p.fiscal_year)
    return year_out(p.fiscal_year)
