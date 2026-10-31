"""Items, units, groups, barcodes, prices, scale-barcode rules and the POS lookup."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from nextcam_core import CoreError
from nextcam_core.scan import (
    ScaleRule,
    ean13_check_digit,
    is_scale_label,
    normalize_scan,
    parse_scale,
)
from sqlalchemy import func, or_, select, text, true
from sqlalchemy.orm import Session

from app.core import refcache
from app.core.db import utcnow, version_to_str
from app.core.errors import ConflictError, DomainError, NotFoundError, PermissionDeniedError
from app.core.http import Page
from app.core.money import MONEY_PLACES
from app.modules.accounting.services.chart import check_version
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.inventory.models import (
    Item,
    ItemBarcode,
    ItemGroup,
    ItemPrice,
    ItemUnit,
    PriceList,
    ScaleBarcodeRule,
    StockBalance,
    Unit,
)
from app.modules.inventory.schemas import (
    BarcodeIO,
    GroupIn,
    GroupOut,
    ItemIn,
    ItemOut,
    ItemQuery,
    ItemSummary,
    ItemUnitIO,
    LookupOut,
    OpeningStockIn,
    PriceIO,
    PriceListOut,
    ScaleRuleIn,
    ScaleRuleOut,
    StockDocIn,
    StockLineIn,
    UnitOut,
)
from app.modules.inventory.services import images

DEFAULT_UNITS = (
    ("PCS", "عدد", False),
    ("KG", "کیلوگرم", True),
    ("G", "گرم", True),
    ("L", "لیتر", True),
    ("PACK", "بسته", False),
    ("CTN", "کارتن", False),
    ("BOX", "جعبه", False),
    ("M", "متر", True),
)

# A scanner on a Persian Windows keyboard layout types Persian characters for
# the same keys. Map them back to the US layout the barcode was encoded with.
__all__ = ["ean13_check_digit", "normalize_scan"]


def seed_catalog(s: Session) -> None:
    existing = set(s.scalars(select(Unit.code)))
    for code, name, frac in DEFAULT_UNITS:
        if code not in existing:
            s.add(Unit(code=code, name=name, allows_fraction=frac))
    if s.scalar(select(PriceList.id).limit(1)) is None:
        s.add(PriceList(code="RETAIL", name="قیمت خرده‌فروشی", is_default=True, is_active=True))
    s.flush()


def default_price_list(s: Session) -> PriceList:
    pl = s.scalar(
        select(PriceList)
        .where(PriceList.is_active == true())
        .order_by(PriceList.is_default.desc(), PriceList.code)
    )
    if pl is None:
        raise DomainError("لیست قیمت تعریف نشده است", code="no_price_list")
    return pl


# --- units / groups / price lists -------------------------------------------


def list_units(s: Session) -> list[UnitOut]:
    return [
        UnitOut(id=u.id, code=u.code, name=u.name, allows_fraction=u.allows_fraction)
        for u in s.scalars(select(Unit).order_by(Unit.name))
    ]


def list_groups(s: Session) -> list[GroupOut]:
    return [
        GroupOut(
            id=g.id,
            code=g.code,
            name=g.name,
            parent_id=g.parent_id,
            row_version=version_to_str(g.row_version),
        )
        for g in s.scalars(select(ItemGroup).order_by(ItemGroup.code))
    ]


def create_group(s: Session, actor: Actor, data: GroupIn) -> GroupOut:
    if s.scalar(select(ItemGroup.id).where(ItemGroup.code == data.code)):
        raise ConflictError("کد گروه تکراری است", code="group_code_taken")
    g = ItemGroup(
        code=data.code,
        name=data.name,
        parent_id=data.parent_id,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    s.add(g)
    s.flush()
    audit.record(
        s,
        "inventory.group_created",
        user_id=actor.user_id,
        entity_type="item_group",
        entity_id=g.id,
        data={"code": g.code, "name": g.name},
    )
    return GroupOut(
        id=g.id,
        code=g.code,
        name=g.name,
        parent_id=g.parent_id,
        row_version=version_to_str(g.row_version),
    )


def list_price_lists(s: Session) -> list[PriceListOut]:
    return [
        PriceListOut(
            id=p.id, code=p.code, name=p.name, is_default=p.is_default, is_active=p.is_active
        )
        for p in s.scalars(select(PriceList).order_by(PriceList.is_default.desc(), PriceList.code))
    ]


# --- items ------------------------------------------------------------------


def _item_out(s: Session, it: Item) -> ItemOut:
    unit = s.get(Unit, it.base_unit_id)
    group = s.get(ItemGroup, it.group_id) if it.group_id else None
    prices = list(s.scalars(select(ItemPrice).where(ItemPrice.item_id == it.id)))
    stock = s.scalar(select(func.sum(StockBalance.qty)).where(StockBalance.item_id == it.id))
    return ItemOut(
        id=it.id,
        code=it.code,
        name=it.name,
        group_id=it.group_id,
        group_name=group.name if group else None,
        base_unit_id=it.base_unit_id,
        base_unit_name=unit.name if unit else "",
        item_type=it.item_type,
        is_weighted=it.is_weighted,
        scale_code=it.scale_code,
        track_expiry=it.track_expiry,
        vat_exempt=it.vat_exempt,
        vat_rate=it.vat_rate,
        tax_item_code=it.tax_item_code,
        min_qty=it.min_qty,
        max_qty=it.max_qty,
        is_active=it.is_active,
        units=[ItemUnitIO(unit_id=u.unit_id, factor=u.factor) for u in it.units],
        barcodes=[BarcodeIO(barcode=b.barcode, unit_id=b.unit_id) for b in it.barcodes],
        prices=[
            PriceIO(price_list_id=p.price_list_id, unit_id=p.unit_id, price=p.price) for p in prices
        ],
        stock_qty=stock or Decimal(0),
        images=images.list_images(s, it.id),
        row_version=version_to_str(it.row_version),
    )


def get_item(s: Session, item_id: uuid.UUID) -> Item:
    it = s.get(Item, item_id)
    if it is None:
        raise NotFoundError("کالا یافت نشد")
    return it


def item_out(s: Session, item_id: uuid.UUID) -> ItemOut:
    return _item_out(s, get_item(s, item_id))


def _validate(s: Session, data: ItemIn, item_id: uuid.UUID | None) -> None:
    if s.get(Unit, data.base_unit_id) is None:
        raise DomainError("واحد اصلی نامعتبر است", code="invalid_unit")
    if data.group_id and s.get(ItemGroup, data.group_id) is None:
        raise DomainError("گروه کالا نامعتبر است", code="invalid_group")
    if data.is_weighted and data.item_type != "goods":
        raise DomainError("خدمت نمی‌تواند وزنی باشد", code="invalid_item")
    alt_units = {u.unit_id for u in data.units}
    if data.base_unit_id in alt_units:
        raise DomainError("واحد اصلی نباید در واحدهای فرعی تکرار شود", code="invalid_unit")
    if len(alt_units) != len(data.units):
        raise DomainError("واحد فرعی تکراری است", code="invalid_unit")
    for u in data.units:
        if u.factor <= 0:
            raise DomainError("ضریب تبدیل باید مثبت باشد", code="invalid_factor")
    known = alt_units | {data.base_unit_id}
    codes = [normalize_scan(b.barcode) for b in data.barcodes]
    if len(set(codes)) != len(codes):
        raise DomainError("بارکد تکراری در فهرست کالا", code="duplicate_barcode")
    for b in data.barcodes:
        if b.unit_id and b.unit_id not in known:
            raise DomainError("واحد بارکد در واحدهای کالا تعریف نشده است", code="invalid_unit")
    if codes:
        clash = s.execute(
            select(ItemBarcode.barcode, Item.code)
            .join(Item, Item.id == ItemBarcode.item_id)
            .where(
                ItemBarcode.barcode.in_(codes), ItemBarcode.item_id != (item_id or uuid.UUID(int=0))
            )
        ).first()
        if clash:
            raise ConflictError(
                f"بارکد {clash[0]} قبلاً برای کالای {clash[1]} ثبت شده است", code="barcode_taken"
            )
    rules = scale_rules(s)
    for code in codes:
        if is_scale_label(code, rules):
            raise DomainError(
                f"بارکد {code} با پیشوند بارکد ترازو شروع می‌شود و قابل ثبت نیست",
                code="barcode_scale_prefix",
            )
    if data.scale_code:
        q = select(Item.code).where(Item.scale_code == data.scale_code)
        if item_id:
            q = q.where(Item.id != item_id)
        other = s.scalar(q)
        if other:
            raise ConflictError(
                f"کد ترازو {data.scale_code} برای کالای {other} ثبت شده است",
                code="scale_code_taken",
            )
    for p in data.prices:
        if p.unit_id and p.unit_id not in known:
            raise DomainError("واحد قیمت در واحدهای کالا تعریف نشده است", code="invalid_unit")


def _apply(s: Session, it: Item, data: ItemIn, actor: Actor) -> dict[str, str]:
    """Write fields, units, barcodes, prices. Returns price changes for the audit trail."""
    for f in (
        "code",
        "name",
        "group_id",
        "base_unit_id",
        "item_type",
        "is_weighted",
        "scale_code",
        "track_expiry",
        "vat_exempt",
        "vat_rate",
        "tax_item_code",
        "min_qty",
        "max_qty",
        "is_active",
    ):
        setattr(it, f, getattr(data, f))
    # Diff child rows: delete-then-insert would trip the unique keys inside one flush.
    want_units = {u.unit_id: u.factor for u in data.units}
    for u in list(it.units):
        if u.unit_id not in want_units:
            it.units.remove(u)
        else:
            u.factor = want_units.pop(u.unit_id)
    for unit_id, factor in want_units.items():
        it.units.append(ItemUnit(unit_id=unit_id, factor=factor))
    want_codes = {normalize_scan(b.barcode): b.unit_id for b in data.barcodes}
    for b in list(it.barcodes):
        if b.barcode not in want_codes:
            it.barcodes.remove(b)
        else:
            b.unit_id = want_codes.pop(b.barcode)
    s.flush()
    for code, barcode_unit in want_codes.items():
        it.barcodes.append(ItemBarcode(barcode=code, unit_id=barcode_unit))

    changes: dict[str, str] = {}
    if data.prices:
        default_pl = default_price_list(s).id
        current = {
            (p.price_list_id, p.unit_id): p
            for p in s.scalars(select(ItemPrice).where(ItemPrice.item_id == it.id))
        }
        for p in data.prices:
            key = (p.price_list_id or default_pl, p.unit_id or data.base_unit_id)
            row = current.get(key)
            if row is None:
                s.add(
                    ItemPrice(
                        price_list_id=key[0],
                        item_id=it.id,
                        unit_id=key[1],
                        price=p.price,
                        created_by=actor.user_id,
                    )
                )
                changes[str(key[1])] = f"→{p.price}"
            elif row.price != p.price:
                changes[str(key[1])] = f"{row.price}→{p.price}"
                row.price = p.price
    return changes


def create_item(s: Session, actor: Actor, data: ItemIn) -> ItemOut:
    if s.scalar(select(Item.id).where(Item.code == data.code)):
        raise ConflictError("کد کالا تکراری است", code="item_code_taken")
    _validate(s, data, None)
    if data.opening is not None and not actor.has("inventory.stock.create"):
        raise PermissionDeniedError("ثبت موجودی اولیه مجوز ثبت سند انبار لازم دارد")
    it = Item(created_by=actor.user_id, updated_by=actor.user_id)
    s.add(it)
    _apply(s, it, data, actor)
    s.flush()
    audit.record(
        s,
        "inventory.item_created",
        user_id=actor.user_id,
        entity_type="item",
        entity_id=it.id,
        data={"code": it.code, "name": it.name},
    )
    if data.opening is not None:
        _opening(s, actor, it, data.opening)
    return _item_out(s, it)


def _opening(s: Session, actor: Actor, it: Item, o: OpeningStockIn) -> None:
    """An ordinary opening stock document, finalized in the same transaction: a failure
    (closed fiscal year, missing expiry date) leaves neither the item nor the stock."""
    from app.modules.inventory.services import stock

    if it.item_type != "goods":
        raise DomainError("خدمت موجودی ندارد", code="service_has_no_stock")
    doc = stock.create_doc(
        s,
        actor,
        StockDocIn(
            doc_type="opening",
            warehouse_id=o.warehouse_id,
            document_date=stock.tehran_today(),
            description=f"موجودی اولیه‌ی کالای {it.name}",
            lines=[
                StockLineIn(
                    item_id=it.id,
                    unit_id=it.base_unit_id,
                    qty=o.qty,
                    unit_cost=o.unit_cost,
                    expiry_date=o.expiry_date,
                )
            ],
        ),
    )
    stock.finalize_doc(s, actor, doc.id, doc.row_version)


def update_item(
    s: Session, actor: Actor, item_id: uuid.UUID, data: ItemIn, version: str
) -> ItemOut:
    if data.opening is not None:
        raise DomainError(
            "موجودی کالای موجود را با سند انبار ثبت کنید", code="opening_on_create_only"
        )
    it = get_item(s, item_id)
    check_version(it.row_version, version, "این کالا")
    if data.code != it.code and s.scalar(select(Item.id).where(Item.code == data.code)):
        raise ConflictError("کد کالا تکراری است", code="item_code_taken")
    if data.base_unit_id != it.base_unit_id and s.scalar(
        select(StockBalance.item_id).where(StockBalance.item_id == it.id).limit(1)
    ):
        raise DomainError("کالای دارای گردش انبار: واحد اصلی قابل تغییر نیست", code="unit_locked")
    _validate(s, data, it.id)
    price_changes = _apply(s, it, data, actor)
    it.updated_by = actor.user_id
    it.updated_at = utcnow()
    s.flush()
    s.refresh(it)
    audit.record(
        s,
        "inventory.item_updated",
        user_id=actor.user_id,
        entity_type="item",
        entity_id=it.id,
        data={"code": it.code},
    )
    if price_changes:
        audit.record(
            s,
            "inventory.price_changed",
            user_id=actor.user_id,
            entity_type="item",
            entity_id=it.id,
            data={"code": it.code, "changes": price_changes},
        )
    return _item_out(s, it)


def list_items(s: Session, q: ItemQuery) -> Page[ItemSummary]:
    pl = default_price_list(s).id
    stock = (
        select(StockBalance.item_id, func.sum(StockBalance.qty).label("qty"))
        .group_by(StockBalance.item_id)
        .subquery()
    )
    first_barcode = (
        select(func.min(ItemBarcode.barcode))
        .where(ItemBarcode.item_id == Item.id)
        .correlate(Item)
        .scalar_subquery()
    )
    price = (
        select(ItemPrice.price)
        .where(
            ItemPrice.item_id == Item.id,
            ItemPrice.price_list_id == pl,
            ItemPrice.unit_id == Item.base_unit_id,
        )
        .correlate(Item)
        .scalar_subquery()
    )
    stmt = (
        select(Item, Unit.name, ItemGroup.name, first_barcode, price, func.coalesce(stock.c.qty, 0))
        .join(Unit, Unit.id == Item.base_unit_id)
        .outerjoin(ItemGroup, ItemGroup.id == Item.group_id)
        .outerjoin(stock, stock.c.item_id == Item.id)
    )
    if q.q:
        raw = q.q.strip()
        term = normalize_scan(raw)  # a scan typed on a Persian keyboard layout
        stmt = stmt.where(
            or_(
                Item.code == term,
                Item.code.like(f"{raw}%"),
                Item.name.like(f"%{raw}%"),
                Item.id.in_(select(ItemBarcode.item_id).where(ItemBarcode.barcode == term)),
            )
        )
    if q.group_id:
        stmt = stmt.where(Item.group_id == q.group_id)
    if q.active is not None:
        stmt = stmt.where(Item.is_active == q.active)
    if q.below_min:
        stmt = stmt.where(Item.min_qty.is_not(None), func.coalesce(stock.c.qty, 0) < Item.min_qty)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = s.execute(
        stmt.order_by(Item.code).offset((q.page - 1) * q.page_size).limit(q.page_size)
    ).all()
    photos = images.image_ids(s, [r[0].id for r in rows])
    items = [
        ItemSummary(
            id=it.id,
            code=it.code,
            name=it.name,
            group_name=gname,
            base_unit_name=uname,
            is_weighted=it.is_weighted,
            is_active=it.is_active,
            barcode=bc,
            price=pr,
            stock_qty=sq or Decimal(0),
            image_id=next(iter(photos.get(it.id, [])), None),
        )
        for it, uname, gname, bc, pr, sq in rows
    ]
    return Page[ItemSummary](items=items, total=total, page=q.page, page_size=q.page_size)


# --- scale rules ------------------------------------------------------------


def scale_rules(s: Session) -> list[ScaleRule]:
    """The active scale rules (reference data, cached; cleared when a rule is saved)."""
    return list(
        refcache.get(
            "scale_rules",
            lambda: tuple(
                ScaleRule(
                    r.prefix, r.item_code_length, r.value_type, r.value_decimals, r.check_digit
                )
                for r in s.scalars(
                    select(ScaleBarcodeRule).where(ScaleBarcodeRule.is_active == true())
                )
            ),
        )
    )


def _rule_out(r: ScaleBarcodeRule) -> ScaleRuleOut:
    return ScaleRuleOut(
        id=r.id,
        name=r.name,
        prefix=r.prefix,
        item_code_length=r.item_code_length,
        value_length=r.value_length,
        value_type=r.value_type,  # type: ignore[arg-type]
        value_decimals=r.value_decimals,
        check_digit=r.check_digit,
        is_active=r.is_active,
        row_version=version_to_str(r.row_version),
    )


def list_scale_rules(s: Session) -> list[ScaleRuleOut]:
    return [
        _rule_out(r) for r in s.scalars(select(ScaleBarcodeRule).order_by(ScaleBarcodeRule.prefix))
    ]


def _check_rule(data: ScaleRuleIn) -> None:
    if len(data.prefix) + data.item_code_length + data.value_length != 12:
        raise DomainError(
            "جمع طول پیشوند، کد کالا و مقدار باید ۱۲ رقم باشد (رقم کنترل، اگر باشد، جدا است)",
            code="invalid_rule",
        )


def save_scale_rule(
    s: Session,
    actor: Actor,
    data: ScaleRuleIn,
    rule_id: uuid.UUID | None = None,
    version: str | None = None,
) -> ScaleRuleOut:
    refcache.invalidate_after_commit(s)
    _check_rule(data)
    others = select(ScaleBarcodeRule).where(ScaleBarcodeRule.id != (rule_id or uuid.UUID(int=0)))
    for r in list(s.scalars(others)):
        if r.prefix.startswith(data.prefix) or data.prefix.startswith(r.prefix):
            raise ConflictError(
                f"پیشوند {data.prefix} با قاعده «{r.name}» تداخل دارد", code="prefix_overlap"
            )
    if rule_id is None:
        r = ScaleBarcodeRule(created_by=actor.user_id)
        s.add(r)
    else:
        found = s.get(ScaleBarcodeRule, rule_id)
        if found is None:
            raise NotFoundError("قاعده یافت نشد")
        check_version(found.row_version, version or "", "این قاعده")
        r = found
        r.updated_at = utcnow()
    for k, v in data.model_dump().items():
        setattr(r, k, v)
    r.updated_by = actor.user_id
    s.flush()
    s.refresh(r)
    audit.record(
        s,
        "inventory.scale_rule_saved",
        user_id=actor.user_id,
        entity_type="scale_barcode_rule",
        entity_id=r.id,
        data=data.model_dump(),
    )
    return _rule_out(r)


# --- POS lookup (hot path) --------------------------------------------------


def _price(s: Session, item: Item, unit_id: uuid.UUID, price_list_id: uuid.UUID) -> Decimal | None:
    """Price of the unit; without one, the base-unit price times the unit's factor."""
    prices = {
        p.unit_id: p.price
        for p in s.scalars(
            select(ItemPrice).where(
                ItemPrice.item_id == item.id, ItemPrice.price_list_id == price_list_id
            )
        )
    }
    if unit_id in prices:
        return prices[unit_id]
    base = prices.get(item.base_unit_id)
    if base is None or unit_id == item.base_unit_id:
        return base
    factor = s.scalar(
        select(ItemUnit.factor).where(ItemUnit.item_id == item.id, ItemUnit.unit_id == unit_id)
    )
    return (base * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP) if factor else None


def lookup(s: Session, raw: str, price_list_id: uuid.UUID | None = None) -> LookupOut:
    code = normalize_scan(raw)
    if not code:
        raise DomainError("بارکد خالی است", code="empty_barcode")
    pl = price_list_id or refcache.get("price_list", lambda: default_price_list(s).id)

    def result(
        item: Item, unit_id: uuid.UUID, qty: Decimal, source: str, line_price: Decimal | None = None
    ) -> LookupOut:
        if not item.is_active:
            raise DomainError(f"کالای «{item.name}» غیرفعال است", code="item_inactive")
        unit = s.get(Unit, unit_id)
        unit_price = _price(s, item, unit_id, pl)
        if line_price is None and unit_price is not None:
            line_price = (unit_price * qty).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
        return LookupOut(
            item_id=item.id,
            code=item.code,
            name=item.name,
            unit_id=unit_id,
            unit_name=unit.name if unit else "",
            qty=qty,
            unit_price=unit_price,
            line_price=line_price,
            source=source,  # type: ignore[arg-type]
            is_weighted=item.is_weighted,
            vat_exempt=item.vat_exempt,
            vat_rate=item.vat_rate,
        )

    row = s.execute(
        select(ItemBarcode, Item)
        .join(Item, Item.id == ItemBarcode.item_id)
        .where(ItemBarcode.barcode == code)
    ).first()
    if row:
        bc, item = row
        return result(
            item,
            bc.unit_id or item.base_unit_id,
            Decimal(1),
            "pack_barcode" if bc.unit_id else "barcode",
        )

    rules = scale_rules(s)
    if is_scale_label(code, rules):

        def find_plu(plu: str) -> uuid.UUID | None:
            return s.scalar(
                select(Item.id).where(
                    or_(Item.scale_code == plu, Item.scale_code == plu.lstrip("0"))
                )
            )

        def base_price(item_id: uuid.UUID) -> Decimal | None:
            it = s.get(Item, item_id)
            return _price(s, it, it.base_unit_id, pl) if it else None

        try:
            hit = parse_scale(code, rules, find_plu, base_price)
        except CoreError as e:
            if e.not_found:
                raise NotFoundError(e.message) from e
            raise DomainError(e.message, code=e.code) from e
        if hit is not None:
            scaled = s.get(Item, hit.item_id)
            assert scaled is not None
            return result(
                scaled, scaled.base_unit_id, hit.qty, hit.source, line_price=hit.line_price
            )

    by_code = s.scalar(select(Item).where(Item.code == code))
    if by_code is not None:
        return result(by_code, by_code.base_unit_id, Decimal(1), "code")
    raise NotFoundError(f"کالایی با بارکد {code} یافت نشد")


def next_code(s: Session) -> str:
    """The next free numeric item code (largest numeric code + 1, same width), as a
    suggestion the user may replace with the company's own code (ADR-0029)."""
    row = s.execute(
        text(
            "SELECT TOP 1 code FROM item WHERE code NOT LIKE '%[^0-9]%' AND LEN(code) <= 18 "
            "ORDER BY LEN(code) DESC, code DESC"
        )
    ).first()
    if row is None:
        return "1001"
    current = str(row[0])
    candidate = str(int(current) + 1).zfill(len(current))
    while s.scalar(select(Item.id).where(Item.code == candidate)):
        candidate = str(int(candidate) + 1).zfill(len(current))
    return candidate
