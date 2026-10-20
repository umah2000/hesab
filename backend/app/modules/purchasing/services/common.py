"""Shared lookups for purchasing: suppliers, warehouses, units and rounding."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, NotFoundError
from app.modules.accounting.models import DetailAccount
from app.modules.iam.guard import Actor
from app.modules.inventory.models import Item, ItemUnit, Unit, Warehouse
from app.modules.parties.models import Party

ZERO = Decimal(0)
HUNDRED = Decimal(100)


def rial(d: Decimal) -> Decimal:
    return d.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def warehouse(s: Session, actor: Actor, wid: uuid.UUID) -> Warehouse:
    w = s.get(Warehouse, wid)
    if w is None or not w.is_active or not actor.can_access_branch(w.branch_id):
        raise NotFoundError("انبار یافت نشد")
    return w


def supplier(s: Session, party_id: uuid.UUID) -> tuple[Party, DetailAccount]:
    p = s.get(Party, party_id)
    d = s.get(DetailAccount, party_id)
    if p is None or d is None:
        raise NotFoundError("تأمین‌کننده یافت نشد")
    if not p.is_supplier or not d.is_active:
        raise DomainError("طرف‌حساب انتخاب‌شده تأمین‌کننده فعال نیست", code="not_a_supplier")
    return p, d


def active_party(s: Session, party_id: uuid.UUID) -> DetailAccount:
    d = s.get(DetailAccount, party_id)
    if d is None or s.get(Party, party_id) is None or not d.is_active:
        raise DomainError("طرف‌حساب هزینه یافت نشد یا غیرفعال است", code="bad_payee")
    return d


def items(s: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, Item]:
    found = {i.id: i for i in s.scalars(select(Item).where(Item.id.in_(ids)))}
    for i in ids:
        it = found.get(i)
        if it is None or not it.is_active:
            raise DomainError("کالای انتخاب‌شده یافت نشد یا غیرفعال است", code="bad_item")
        if it.item_type != "goods":
            raise DomainError(f"«{it.name}» کالا نیست؛ خرید خدمت ثبت نمی‌شود", code="not_goods")
    return found


def base_qty(s: Session, item: Item, unit_id: uuid.UUID, qty: Decimal) -> Decimal:
    """Quantity in the item's base unit; fractions only for units that allow them."""
    unit = s.get(Unit, unit_id)
    if unit is None:
        raise DomainError("واحد یافت نشد", code="invalid_unit")
    if not unit.allows_fraction and qty != qty.to_integral_value():
        raise DomainError(
            f"مقدار «{item.name}» در واحد «{unit.name}» باید صحیح باشد", code="fraction"
        )
    if unit_id == item.base_unit_id:
        return qty
    f = s.scalar(
        select(ItemUnit.factor).where(ItemUnit.item_id == item.id, ItemUnit.unit_id == unit_id)
    )
    if f is None:
        raise DomainError(f"واحد انتخاب‌شده برای «{item.name}» تعریف نشده است", code="invalid_unit")
    return (qty * Decimal(f)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def names(s: Session, model: type, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = s.execute(select(model.id, model.name).where(model.id.in_(ids)))  # type: ignore[attr-defined]
    return {k: v for k, v in rows}
