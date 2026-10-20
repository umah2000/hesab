"""Time-boxed promotions: percent or amount off an item or a whole group."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow, version_to_str
from app.core.errors import DomainError, NotFoundError
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.inventory.models import Item, ItemGroup
from app.modules.sales.models import Promotion
from app.modules.sales.schemas import PromotionIn, PromotionOut


def _out(s: Session, p: Promotion) -> PromotionOut:
    target = s.get(Item, p.item_id) if p.item_id else s.get(ItemGroup, p.group_id)
    return PromotionOut(
        id=p.id,
        name=p.name,
        kind=p.kind,  # type: ignore[arg-type]
        scope=p.scope,  # type: ignore[arg-type]
        item_id=p.item_id,
        group_id=p.group_id,
        target_name=target.name if target else "",
        value=p.value,
        starts_on=p.starts_on,
        ends_on=p.ends_on,
        is_active=p.is_active,
        row_version=version_to_str(p.row_version),
    )


def _validate(s: Session, data: PromotionIn) -> None:
    if data.ends_on < data.starts_on:
        raise DomainError("تاریخ پایان قبل از شروع است", code="bad_dates")
    if data.kind == "percent" and data.value > 100:
        raise DomainError("درصد تخفیف حداکثر ۱۰۰ است", code="bad_value")
    if data.scope == "item":
        if data.item_id is None or data.group_id is not None or s.get(Item, data.item_id) is None:
            raise DomainError("کالای پروموشن را انتخاب کنید", code="bad_target")
    elif (
        data.group_id is None or data.item_id is not None or s.get(ItemGroup, data.group_id) is None
    ):
        raise DomainError("گروه پروموشن را انتخاب کنید", code="bad_target")


def list_promotions(s: Session) -> list[PromotionOut]:
    rows = list(s.scalars(select(Promotion).order_by(Promotion.starts_on.desc(), Promotion.name)))
    return [_out(s, p) for p in rows]


def save(
    s: Session,
    actor: Actor,
    data: PromotionIn,
    promotion_id: uuid.UUID | None = None,
    version: str | None = None,
) -> PromotionOut:
    _validate(s, data)
    if promotion_id is None:
        p = Promotion(created_by=actor.user_id)
        s.add(p)
    else:
        found = s.get(Promotion, promotion_id)
        if found is None:
            raise NotFoundError("پروموشن یافت نشد")
        check_version(found.row_version, version or "", "این پروموشن")
        p = found
        p.updated_at = utcnow()
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    p.updated_by = actor.user_id
    s.flush()
    s.refresh(p)
    audit.record(
        s,
        "sales.promotion_saved",
        user_id=actor.user_id,
        entity_type="promotion",
        entity_id=p.id,
        data=data.model_dump(mode="json"),
    )
    return _out(s, p)
