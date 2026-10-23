"""What a register needs to keep selling while the server is out of reach (ADR-0017).

A full copy for one register: its catalogue, default price list, barcodes, scale rules,
promotions, settings and open shift. The version is a hash of the content, so an
unchanged snapshot is answered with 304 and costs the agent nothing to keep.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.errors import DomainError
from app.modules.devices.models import Device
from app.modules.iam.models import AppUser
from app.modules.inventory.models import (
    Item,
    ItemBarcode,
    ItemPrice,
    ItemUnit,
    ScaleBarcodeRule,
    StockBalance,
    Unit,
)
from app.modules.inventory.services.stock import tehran_today
from app.modules.organization.models import Branch
from app.modules.sales.models import Promotion
from app.modules.sales.services.pricing import (
    default_price_list_id,
    organization,
    register_and_warehouse,
)
from app.modules.sales.services.shifts import open_shift_on
from app.modules.sync.schemas import (
    SnapBarcode,
    SnapFactor,
    SnapItem,
    SnapPrice,
    SnapPromotion,
    SnapRegister,
    SnapScaleRule,
    SnapSettings,
    SnapShift,
    SnapshotOut,
    SnapUnit,
)

# How long a register may sell on an old snapshot before it must reach the server.
VALID_FOR = timedelta(hours=24)


def number_prefix(d: Device) -> str:
    """Offline receipt numbers: ``<prefix>-<sequence>``, unique across devices."""
    return d.id.hex[:8].upper()


def snapshot(s: Session, d: Device) -> SnapshotOut:
    if d.cash_register_id is None:
        raise DomainError("این دستگاه به صندوقی وصل نیست", code="no_register")
    reg, wh = register_and_warehouse(s, d.cash_register_id, None)
    branch = s.get(Branch, reg.branch_id)
    org = organization(s)
    pl_id = default_price_list_id(s)
    today = tehran_today()

    shift_out = None
    sh = open_shift_on(s, reg.id)
    if sh is not None:
        user = s.get(AppUser, sh.user_id)
        if user is not None and user.is_active:
            shift_out = SnapShift(
                id=sh.id,
                user_id=user.id,
                username=user.username,
                user_name=user.full_name or user.username,
                opened_at=sh.opened_at,
                opening_cash=sh.opening_cash,
                permissions=sorted(p for p in user.permission_codes if p.startswith("sales.")),
            )

    stock = {
        b.item_id: b.qty
        for b in s.scalars(select(StockBalance).where(StockBalance.warehouse_id == wh.id))
    }
    items = [
        SnapItem(
            id=i.id,
            code=i.code,
            name=i.name,
            group_id=i.group_id,
            base_unit_id=i.base_unit_id,
            item_type=i.item_type,
            is_weighted=i.is_weighted,
            scale_code=i.scale_code,
            vat_exempt=i.vat_exempt,
            vat_rate=i.vat_rate,
            stock=stock.get(i.id) if i.item_type == "goods" else None,
        )
        for i in s.scalars(select(Item).where(Item.is_active == true()).order_by(Item.code))
    ]
    active = {i.id for i in items}
    out = SnapshotOut(
        version="",
        generated_at=utcnow().replace(microsecond=0),
        valid_until=utcnow().replace(microsecond=0) + VALID_FOR,
        number_prefix=number_prefix(d),
        cash_register=SnapRegister(
            id=reg.id,
            code=reg.code,
            name=reg.name,
            branch_id=reg.branch_id,
            branch_name=branch.name if branch else "",
            warehouse_id=wh.id,
        ),
        shift=shift_out,
        settings=SnapSettings(
            organization_name=org.name,
            timezone=org.timezone,
            display_currency=org.display_currency,
            default_vat_rate=org.default_vat_rate,
            prices_include_vat=org.prices_include_vat,
            cashier_discount_limit=org.cashier_discount_limit,
            negative_stock_policy=org.negative_stock_policy,
            receipt_header=org.receipt_header,
            receipt_footer=org.receipt_footer,
            phone=org.phone,
            address=org.address,
        ),
        units=[
            SnapUnit(id=u.id, name=u.name, allows_fraction=u.allows_fraction)
            for u in s.scalars(select(Unit).order_by(Unit.code))
        ],
        items=items,
        factors=[
            SnapFactor(item_id=u.item_id, unit_id=u.unit_id, factor=u.factor)
            for u in s.scalars(select(ItemUnit))
            if u.item_id in active
        ],
        prices=[
            SnapPrice(item_id=p.item_id, unit_id=p.unit_id, price=p.price)
            for p in s.scalars(select(ItemPrice).where(ItemPrice.price_list_id == pl_id))
            if p.item_id in active
        ],
        barcodes=[
            SnapBarcode(barcode=b.barcode, item_id=b.item_id, unit_id=b.unit_id)
            for b in s.scalars(select(ItemBarcode).order_by(ItemBarcode.barcode))
            if b.item_id in active
        ],
        scale_rules=[
            SnapScaleRule(
                prefix=r.prefix,
                item_code_length=r.item_code_length,
                value_type=r.value_type,
                value_decimals=r.value_decimals,
                check_digit=r.check_digit,
            )
            for r in s.scalars(
                select(ScaleBarcodeRule)
                .where(ScaleBarcodeRule.is_active == true())
                .order_by(ScaleBarcodeRule.prefix)
            )
        ],
        promotions=[
            SnapPromotion(
                id=p.id,
                name=p.name,
                kind=p.kind,
                value=p.value,
                item_id=p.item_id,
                group_id=p.group_id,
                starts_on=p.starts_on,
                ends_on=p.ends_on,
            )
            for p in s.scalars(
                select(Promotion)
                .where(Promotion.is_active == true(), Promotion.ends_on >= today)
                .order_by(Promotion.starts_on, Promotion.name)
            )
        ],
    )
    # The version ignores the timestamps, so it changes only when the content does.
    body = out.model_dump(mode="json", exclude={"version", "generated_at", "valid_until"})
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    out.version = hashlib.sha256(raw).hexdigest()[:32]
    return out
