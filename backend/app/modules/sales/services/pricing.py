"""Cart pricing on the server: list price, scale labels, promotions, discounts and VAT.

The POS shows whatever this returns; checkout prices the cart again with the same code,
so a number sent by the browser is never trusted (posting-rules.md §4, ADR-0013).
Amounts are whole rials.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from nextcam_core import CoreError
from nextcam_core.pricing import ItemRef, LineIn, PricedCart, PricedLine, PromoRef, fmt_qty, rial
from nextcam_core.pricing import Settings as CoreSettings
from nextcam_core.pricing import price_cart as core_price_cart
from nextcam_core.scan import LabelHit, is_scale_label
from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.core import refcache
from app.core.errors import DomainError, NotFoundError
from app.modules.inventory.models import (
    Item,
    ItemPrice,
    ItemUnit,
    StockBalance,
    Unit,
    Warehouse,
)
from app.modules.inventory.services import catalog
from app.modules.organization.models import CashRegister, Organization
from app.modules.sales.models import Promotion
from app.modules.sales.schemas import (
    CartIn,
    PriceTicketIn,
    PriceTicketOut,
    PriceTicketsOut,
    QuoteLineOut,
    QuoteOut,
)

ZERO = Decimal(0)
__all__ = [
    "LineIn",
    "PricedCart",
    "PricedLine",
    "fmt_qty",
    "price_cart",
    "price_lines",
    "quote_out",
    "rial",
]


def domain_error(e: CoreError) -> DomainError:
    return NotFoundError(e.message) if e.not_found else DomainError(e.message, code=e.code)


def line_out(ln: PricedLine) -> QuoteLineOut:
    return QuoteLineOut(
        line_no=ln.line_no,
        item_id=ln.item.id,
        item_code=ln.item.code,
        item_name=ln.item.name,
        unit_id=ln.unit_id,
        unit_name=ln.unit_name,
        qty=ln.qty,
        unit_price=ln.unit_price,
        price_source=ln.price_source,  # type: ignore[arg-type]
        gross=ln.gross,
        promotion_id=ln.promotion.id if ln.promotion else None,
        promotion_name=ln.promotion.name if ln.promotion else None,
        promotion_discount=ln.promotion_discount,
        manual_discount=ln.manual_discount,
        vat_exempt=ln.vat_exempt,
        vat_rate=ln.vat_rate,
        tax=ln.tax,
        line_total=ln.line_total,
        stock_qty=ln.stock_qty,
        scanned_barcode=ln.scanned_barcode,
    )


def quote_out(cart: PricedCart) -> QuoteOut:
    return QuoteOut(
        lines=[line_out(ln) for ln in cart.lines],
        subtotal=cart.subtotal,
        promotion_total=cart.promotion_total,
        manual_discount_total=cart.manual_discount_total,
        discount_total=cart.discount_total,
        tax_total=cart.tax_total,
        grand_total=cart.grand_total,
        manual_discount_percent=cart.manual_percent,
        discount_limit_percent=cart.limit_percent,
        needs_discount_approval=cart.needs_discount_approval,
        warnings=cart.warnings,
    )


@dataclass(frozen=True)
class SalesSettings:
    name: str
    timezone: str
    display_currency: str
    negative_stock_policy: str
    default_vat_rate: Decimal
    prices_include_vat: bool
    cashier_discount_limit: Decimal
    receipt_header: str | None
    receipt_footer: str | None
    phone: str | None
    address: str | None
    invoice_paper: str


@dataclass(frozen=True)
class RegisterRef:
    id: uuid.UUID
    branch_id: uuid.UUID
    code: str
    name: str


@dataclass(frozen=True)
class WarehouseRef:
    id: uuid.UUID


def organization(s: Session) -> SalesSettings:
    def load() -> SalesSettings:
        org: Organization | None = s.scalar(select(Organization))
        if org is None:
            raise DomainError("سازمان تعریف نشده است", code="no_organization")
        return SalesSettings(
            name=org.name,
            timezone=org.timezone,
            display_currency=org.display_currency,
            negative_stock_policy=org.negative_stock_policy,
            default_vat_rate=org.default_vat_rate,
            prices_include_vat=org.prices_include_vat,
            cashier_discount_limit=org.cashier_discount_limit,
            receipt_header=org.receipt_header,
            receipt_footer=org.receipt_footer,
            phone=org.phone,
            address=org.address,
            invoice_paper=org.invoice_paper,
        )

    return refcache.get("organization", load)


def register_and_warehouse(
    s: Session, register_id: uuid.UUID, branch_ids: frozenset[uuid.UUID] | None
) -> tuple[RegisterRef, WarehouseRef]:
    def load() -> tuple[RegisterRef, bool, WarehouseRef | None] | None:
        reg = s.get(CashRegister, register_id)
        if reg is None:
            return None
        # The branch's first active warehouse (by code) is the shop floor.
        wh = s.scalar(
            select(Warehouse.id)
            .where(Warehouse.branch_id == reg.branch_id, Warehouse.is_active == true())
            .order_by(Warehouse.code)
        )
        return (
            RegisterRef(reg.id, reg.branch_id, reg.code, reg.name),
            reg.is_active,
            WarehouseRef(wh) if wh else None,
        )

    found = refcache.get(f"register:{register_id}", load)
    if found is None or (branch_ids is not None and found[0].branch_id not in branch_ids):
        raise NotFoundError("صندوق یافت نشد")
    reg, active, wh = found
    if not active:
        raise DomainError("این صندوق غیرفعال است", code="register_inactive")
    if wh is None:
        raise DomainError("برای این شعبه انباری تعریف نشده است", code="no_warehouse")
    return reg, wh


def default_price_list_id(s: Session) -> uuid.UUID:
    return refcache.get("price_list", lambda: catalog.default_price_list(s).id)


def _unit_names(s: Session) -> dict[uuid.UUID, str]:
    return refcache.get("units", lambda: {u.id: u.name for u in s.scalars(select(Unit))})


def _is_scale_label(s: Session, code: str) -> bool:
    return is_scale_label(code, catalog.scale_rules(s))


def item_ref(i: Item) -> ItemRef:
    return ItemRef(
        id=i.id,
        code=i.code,
        name=i.name,
        group_id=i.group_id,
        base_unit_id=i.base_unit_id,
        item_type=i.item_type,
        is_active=i.is_active,
        is_weighted=i.is_weighted,
        vat_exempt=i.vat_exempt,
        vat_rate=i.vat_rate,
    )


class DbCatalog:
    """nextcam_core.pricing.Catalog over SQL Server, loaded in a few batched queries."""

    def __init__(self, s: Session, warehouse_id: uuid.UUID) -> None:
        self.s, self.warehouse_id = s, warehouse_id
        self.pl_id = default_price_list_id(s)
        self._factors: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
        self._prices: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
        self._stock: dict[uuid.UUID, Decimal] = {}

    def items(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, ItemRef]:
        s = self.s
        found = {i.id: item_ref(i) for i in s.scalars(select(Item).where(Item.id.in_(ids)))}
        self._factors = {
            (u.item_id, u.unit_id): u.factor
            for u in s.scalars(select(ItemUnit).where(ItemUnit.item_id.in_(ids)))
        }
        self._prices = {
            (p.item_id, p.unit_id): p.price
            for p in s.scalars(
                select(ItemPrice).where(
                    ItemPrice.item_id.in_(ids), ItemPrice.price_list_id == self.pl_id
                )
            )
        }
        self._stock = {
            b.item_id: b.qty
            for b in s.scalars(
                select(StockBalance).where(
                    StockBalance.item_id.in_(ids), StockBalance.warehouse_id == self.warehouse_id
                )
            )
        }
        return found

    def factor(self, item_id: uuid.UUID, unit_id: uuid.UUID) -> Decimal | None:
        return self._factors.get((item_id, unit_id))

    def price(self, item_id: uuid.UUID, unit_id: uuid.UUID) -> Decimal | None:
        return self._prices.get((item_id, unit_id))

    def unit_name(self, unit_id: uuid.UUID) -> str:
        return _unit_names(self.s).get(unit_id, "")

    def unit_allows_fraction(self, unit_id: uuid.UUID) -> bool:
        unit = self.s.get(Unit, unit_id)
        return bool(unit and unit.allows_fraction)

    def stock(self, item_id: uuid.UUID) -> Decimal:
        return self._stock.get(item_id, ZERO)

    def promotions(
        self, item_ids: list[uuid.UUID], group_ids: list[uuid.UUID], today: date
    ) -> list[PromoRef]:
        return [
            PromoRef(p.id, p.name, p.kind, p.value, p.item_id, p.group_id)
            for p in self.s.scalars(
                select(Promotion).where(
                    Promotion.is_active == true(),
                    Promotion.starts_on <= today,
                    Promotion.ends_on >= today,
                    or_(
                        Promotion.item_id.in_(item_ids),
                        Promotion.group_id.in_(group_ids or [uuid.UUID(int=0)]),
                    ),
                )
            )
        ]

    def is_scale_label(self, code: str) -> bool:
        return _is_scale_label(self.s, code)

    def scale_label(self, code: str) -> LabelHit:
        found = catalog.lookup(self.s, code, self.pl_id)
        line_price = found.line_price if found.source == "scale_price" else None
        return LabelHit(found.item_id, found.qty, found.source, line_price)


def core_settings(s: Session) -> CoreSettings:
    org = organization(s)
    return CoreSettings(
        default_vat_rate=org.default_vat_rate,
        prices_include_vat=org.prices_include_vat,
        cashier_discount_limit=org.cashier_discount_limit,
        negative_stock_policy=org.negative_stock_policy,
    )


def price_lines(
    s: Session,
    lines: list[LineIn],
    *,
    warehouse_id: uuid.UUID,
    today: date,
    discount: Decimal = ZERO,
    negative_policy: str | None = None,
) -> PricedCart:
    try:
        return core_price_cart(
            DbCatalog(s, warehouse_id), core_settings(s), lines, discount, today, negative_policy
        )
    except CoreError as e:
        raise domain_error(e) from e


def price_cart(
    s: Session,
    data: CartIn,
    *,
    warehouse_id: uuid.UUID,
    today: date,
    negative_policy: str | None = None,
) -> PricedCart:
    lines = [
        LineIn(
            item_id=inp.item_id,
            qty=inp.qty,
            unit_id=inp.unit_id,
            barcode=inp.barcode,
            manual_discount=inp.manual_discount,
        )
        for inp in data.lines
    ]
    return price_lines(
        s,
        lines,
        warehouse_id=warehouse_id,
        today=today,
        discount=data.discount,
        negative_policy=negative_policy,
    )


TICKET_LIMIT = 500


def price_tickets(s: Session, data: PriceTicketIn, today: date) -> PriceTicketsOut:
    """Shelf tickets: one base unit of each item at the default price list with today's
    promotions, priced by the same code as the register (rule 21)."""
    q = select(Item.id).where(Item.is_active == true())
    if data.item_ids:
        q = q.where(Item.id.in_(data.item_ids))
    elif data.group_id is not None:
        q = q.where(Item.group_id == data.group_id)
    elif not data.promoted_only:
        raise DomainError("کالا، گروه یا «فقط کالاهای تخفیف‌دار» را انتخاب کنید", code="no_items")
    if data.promoted_only:
        promoted = list(
            s.execute(
                select(Promotion.item_id, Promotion.group_id).where(
                    Promotion.is_active == true(),
                    Promotion.starts_on <= today,
                    Promotion.ends_on >= today,
                )
            )
        )
        item_ids = [i for i, _ in promoted if i] or [uuid.UUID(int=0)]
        group_ids = [g for _, g in promoted if g] or [uuid.UUID(int=0)]
        q = q.where(or_(Item.id.in_(item_ids), Item.group_id.in_(group_ids)))
    ids = list(s.scalars(q.order_by(Item.code).limit(TICKET_LIMIT + 1)))
    skipped: list[str] = []
    if len(ids) > TICKET_LIMIT:
        ids = ids[:TICKET_LIMIT]
        skipped.append(f"فقط {TICKET_LIMIT} برچسب اول؛ بقیه را جدا چاپ کنید")
    if not ids:
        return PriceTicketsOut(tickets=[], skipped=skipped)
    cat = DbCatalog(s, uuid.UUID(int=0))  # stock plays no part in a price
    items = cat.items(ids)
    priced = []
    for item_id in ids:
        it = items[item_id]
        if cat.price(it.id, it.base_unit_id) is None:
            skipped.append(f"«{it.name}»: قیمت فروش ندارد")
        else:
            priced.append(LineIn(item_id=it.id, qty=Decimal(1)))
    tickets: list[PriceTicketOut] = []
    if priced:
        try:
            cart = core_price_cart(cat, core_settings(s), priced, ZERO, today, "allow")
        except CoreError as e:
            raise domain_error(e) from e
        weighted = set(
            s.scalars(select(Item.id).where(Item.id.in_(ids), Item.is_weighted == true()))
        )
        for ln in cart.lines:
            final = ln.gross - ln.promotion_discount
            percent = None
            if ln.promotion is not None and ln.promotion_discount:
                value = (
                    ln.promotion.value
                    if ln.promotion.kind == "percent"
                    else ln.promotion_discount * 100 / ln.gross
                )
                percent = format(value.quantize(Decimal("0.01")), "f")
            tickets.append(
                PriceTicketOut(
                    item_id=ln.item.id,
                    code=ln.item.code,
                    name=ln.item.name,
                    unit_name=ln.unit_name,
                    is_weighted=ln.item.id in weighted,
                    price=ln.gross,
                    promotion_name=ln.promotion.name if ln.promotion else None,
                    discount_percent=percent,
                    final_price=final,
                )
            )
    return PriceTicketsOut(tickets=tickets, skipped=skipped)
