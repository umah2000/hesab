"""What the visitor app keeps on the phone to work without a connection (ADR-0018).

Prices here are the list prices of the default price list, for an estimate only: the
server prices every order when it arrives (``orders.submit``). The version is a hash of
the content, so an unchanged catalogue costs the phone a 304.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.distribution.schemas import (
    AppItem,
    AppSettings,
    AppUnit,
    AppVisitor,
    BootstrapOut,
)
from app.modules.distribution.services import visitors
from app.modules.distribution.services.orders import branch_warehouse
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.inventory.models import Item, ItemGroup, ItemPrice, ItemUnit, StockBalance, Unit
from app.modules.organization.models import Branch
from app.modules.sales.services import pricing


def bootstrap(s: Session, actor: Actor) -> BootstrapOut:
    v = visitors.of_actor(s, actor)
    user = s.get(AppUser, v.user_id)
    branch = s.get(Branch, v.branch_id)
    org = pricing.organization(s)
    wh = branch_warehouse(s, v.branch_id)
    pl = pricing.default_price_list_id(s)

    units = {u.id: u for u in s.scalars(select(Unit))}
    groups = {g.id: g.name for g in s.scalars(select(ItemGroup))}
    prices = {
        (p.item_id, p.unit_id): p.price
        for p in s.scalars(select(ItemPrice).where(ItemPrice.price_list_id == pl))
    }
    factors: dict[object, list[ItemUnit]] = {}
    for iu in s.scalars(select(ItemUnit)):
        factors.setdefault(iu.item_id, []).append(iu)
    stock = {
        b.item_id: b.qty
        for b in s.scalars(select(StockBalance).where(StockBalance.warehouse_id == wh))
    }

    items = []
    for i in s.scalars(select(Item).where(Item.is_active == true()).order_by(Item.name)):
        base_price = prices.get((i.id, i.base_unit_id))
        base_unit = units.get(i.base_unit_id)
        app_units = [
            AppUnit(
                unit_id=i.base_unit_id,
                name=base_unit.name if base_unit else "",
                factor=1,  # type: ignore[arg-type]
                price=base_price,
                allows_fraction=i.is_weighted or bool(base_unit and base_unit.allows_fraction),
            )
        ]
        for iu in sorted(factors.get(i.id, []), key=lambda x: x.factor):
            u = units.get(iu.unit_id)
            own = prices.get((i.id, iu.unit_id))
            app_units.append(
                AppUnit(
                    unit_id=iu.unit_id,
                    name=u.name if u else "",
                    factor=iu.factor,
                    price=own
                    if own is not None
                    else (pricing.rial(base_price * iu.factor) if base_price is not None else None),
                    allows_fraction=bool(u and u.allows_fraction),
                )
            )
        items.append(
            AppItem(
                id=i.id,
                code=i.code,
                name=i.name,
                group_name=groups.get(i.group_id) if i.group_id else None,
                base_unit_id=i.base_unit_id,
                units=app_units,
                stock=stock.get(i.id) if i.item_type == "goods" else None,
                vat_exempt=i.vat_exempt,
            )
        )

    out = BootstrapOut(
        version="",
        generated_at=utcnow().replace(microsecond=0),
        visitor=AppVisitor(
            id=v.id,
            code=v.code,
            name=(user.full_name or user.username) if user else "",
            branch_name=branch.name if branch else "",
        ),
        settings=AppSettings(
            organization_name=org.name,
            display_currency=org.display_currency,
            prices_include_vat=org.prices_include_vat,
            default_vat_rate=org.default_vat_rate,
        ),
        customers=visitors.assigned(s, v.id),
        items=items,
    )
    body = out.model_dump(mode="json", exclude={"version", "generated_at"})
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    out.version = hashlib.sha256(raw).hexdigest()[:32]
    return out
