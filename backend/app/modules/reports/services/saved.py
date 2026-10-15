"""Saved report filters: per user, never shared."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.iam.guard import Actor
from app.modules.reports.models import SavedReportFilter
from app.modules.reports.registry import REPORTS, allowed
from app.modules.reports.schemas import SavedFilterIn, SavedFilterOut

MAX_PER_USER = 200


def _out(f: SavedReportFilter) -> SavedFilterOut:
    return SavedFilterOut(
        id=f.id, report=f.report, name=f.name, params=json.loads(f.params), created_at=f.created_at
    )


def list_filters(s: Session, actor: Actor, report: str | None) -> list[SavedFilterOut]:
    stmt = select(SavedReportFilter).where(SavedReportFilter.user_id == actor.user_id)
    if report:
        stmt = stmt.where(SavedReportFilter.report == report)
    return [
        _out(f) for f in s.scalars(stmt.order_by(SavedReportFilter.report, SavedReportFilter.name))
    ]


def create(s: Session, actor: Actor, data: SavedFilterIn) -> SavedFilterOut:
    rep = REPORTS.get(data.report)
    if rep is None or not allowed(actor, rep):
        raise NotFoundError("گزارش یافت نشد")
    # Only the report's own filters are kept, and they must be valid for it.
    params = {k: v for k, v in data.params.items() if k in rep.filters and v not in (None, "")}
    rep.query.model_validate(params)
    raw = json.dumps(params, ensure_ascii=False)
    if len(raw) > 2000:
        raise DomainError("فیلتر بیش از حد بزرگ است", code="filter_too_large")
    count = len(
        list(
            s.scalars(
                select(SavedReportFilter.id).where(SavedReportFilter.user_id == actor.user_id)
            )
        )
    )
    if count >= MAX_PER_USER:
        raise DomainError("حداکثر تعداد فیلتر ذخیره‌شده پر شده است", code="too_many_filters")
    f = SavedReportFilter(user_id=actor.user_id, report=data.report, name=data.name, params=raw)
    s.add(f)
    try:
        s.flush()
    except IntegrityError as e:
        raise ConflictError(
            "فیلتری با این نام برای این گزارش دارید", code="filter_name_taken"
        ) from e
    s.refresh(f)
    return _out(f)


def delete(s: Session, actor: Actor, filter_id: uuid.UUID) -> None:
    f = s.get(SavedReportFilter, filter_id)
    if f is None or f.user_id != actor.user_id:
        raise NotFoundError("فیلتر یافت نشد")
    s.delete(f)
    s.flush()
