"""Cart pricing on the server: list price, scale labels, promotions, discounts and VAT.

The POS shows whatever this returns; checkout prices the cart again with the same code,
so a number sent by the browser is never trusted (posting-rules.md §4, ADR-0013).
Amounts are whole rials.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.core import refcache
from app.core.errors import DomainError, NotFoundError
from app.modules.inventory.models import (
    Item,
    ItemPrice,
    ItemUnit,
    ScaleBarcodeRule,
    StockBalance,
    Unit,
    Warehouse,
)
from app.modules.inventory.services import catalog
from app.modules.organization.models import CashRegister, Organization
from app.modules.sales.models import Promotion
from app.modules.sales.schemas import CartIn, QuoteLineOut, QuoteOut

ZERO = Decimal(0)
RIAL = Decimal(1)
HUNDRED = Decimal(100)


def rial(d: Decimal) -> Decimal:
    return d.quantize(RIAL, rounding=ROUND_HALF_UP)


def fmt_qty(d: Decimal) -> str:
    return format(d.normalize(), "f")


@dataclass
class PricedLine:
    line_no: int
    item: Item
    unit_id: uuid.UUID
    unit_name: str
    factor: Decimal
    qty: Decimal
    base_qty: Decimal
    unit_price: Decimal
    price_source: str
    gross: Decimal
    promotion: Promotion | None
    promotion_discount: Decimal
    manual_discount: Decimal
    vat_exempt: bool
    vat_rate: Decimal
    tax: Decimal = ZERO
    revenue: Decimal = ZERO
    line_total: Decimal = ZERO
    stock_qty: Decimal | None = None
    scanned_barcode: str | None = None

    def out(self) -> QuoteLineOut:
        return QuoteLineOut(
            line_no=self.line_no,
            item_id=self.item.id,
            item_code=self.item.code,
            item_name=self.item.name,
            unit_id=self.unit_id,
            unit_name=self.unit_name,
            qty=self.qty,
            unit_price=self.unit_price,
            price_source=self.price_source,  # type: ignore[arg-type]
            gross=self.gross,
            promotion_id=self.promotion.id if self.promotion else None,
            promotion_name=self.promotion.name if self.promotion else None,
            promotion_discount=self.promotion_discount,
            manual_discount=self.manual_discount,
            vat_exempt=self.vat_exempt,
            vat_rate=self.vat_rate,
            tax=self.tax,
            line_total=self.line_total,
            stock_qty=self.stock_qty,
            scanned_barcode=self.scanned_barcode,
        )


@dataclass
class PricedCart:
    lines: list[PricedLine]
    subtotal: Decimal
    promotion_total: Decimal
    manual_discount_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    manual_percent: Decimal
    limit_percent: Decimal
    warnings: list[str] = field(default_factory=list)
    # Items whose cart quantity exceeds stock: item_id → (name, available, wanted)
    short: dict[uuid.UUID, tuple[str, Decimal, Decimal]] = field(default_factory=dict)

    @property
    def discount_total(self) -> Decimal:
        return self.promotion_total + self.manual_discount_total

    @property
    def needs_discount_approval(self) -> bool:
        return self.manual_discount_total > 0 and self.manual_percent > self.limit_percent

    def out(self) -> QuoteOut:
        return QuoteOut(
            lines=[ln.out() for ln in self.lines],
            subtotal=self.subtotal,
            promotion_total=self.promotion_total,
            manual_discount_total=self.manual_discount_total,
            discount_total=self.discount_total,
            tax_total=self.tax_total,
            grand_total=self.grand_total,
            manual_discount_percent=self.manual_percent,
            discount_limit_percent=self.limit_percent,
            needs_discount_approval=self.needs_discount_approval,
            warnings=self.warnings,
        )


@dataclass(frozen=True)
class SalesSettings:
    name: str
    display_currency: str
    negative_stock_policy: str
    default_vat_rate: Decimal
    prices_include_vat: bool
    cashier_discount_limit: Decimal
    receipt_header: str | None
    receipt_footer: str | None


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
            display_currency=org.display_currency,
            negative_stock_policy=org.negative_stock_policy,
            default_vat_rate=org.default_vat_rate,
            prices_include_vat=org.prices_include_vat,
            cashier_discount_limit=org.cashier_discount_limit,
            receipt_header=org.receipt_header,
            receipt_footer=org.receipt_footer,
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
    if len(code) != 13 or not code.isdigit():
        return False
    prefixes = refcache.get(
        "scale_prefixes",
        lambda: tuple(
            s.scalars(select(ScaleBarcodeRule.prefix).where(ScaleBarcodeRule.is_active == true()))
        ),
    )
    return any(code.startswith(p) for p in prefixes)


def price_cart(
    s: Session,
    data: CartIn,
    *,
    warehouse_id: uuid.UUID,
    today: date,
    negative_policy: str | None = None,
) -> PricedCart:
    org = organization(s)
    policy = negative_policy or org.negative_stock_policy
    ids = list({inp.item_id for inp in data.lines})
    items = {i.id: i for i in s.scalars(select(Item).where(Item.id.in_(ids)))}
    for inp in data.lines:
        if inp.item_id not in items:
            raise NotFoundError("کالا یافت نشد")
    factors = {
        (u.item_id, u.unit_id): u.factor
        for u in s.scalars(select(ItemUnit).where(ItemUnit.item_id.in_(ids)))
    }
    pl_id = default_price_list_id(s)
    prices = {
        (p.item_id, p.unit_id): p.price
        for p in s.scalars(
            select(ItemPrice).where(ItemPrice.item_id.in_(ids), ItemPrice.price_list_id == pl_id)
        )
    }
    unit_names = _unit_names(s)
    group_ids = [i.group_id for i in items.values() if i.group_id]
    promos = list(
        s.scalars(
            select(Promotion).where(
                Promotion.is_active == true(),
                Promotion.starts_on <= today,
                Promotion.ends_on >= today,
                or_(
                    Promotion.item_id.in_(ids),
                    Promotion.group_id.in_(group_ids or [uuid.UUID(int=0)]),
                ),
            )
        )
    )
    stock = {
        b.item_id: b.qty
        for b in s.scalars(
            select(StockBalance).where(
                StockBalance.item_id.in_(ids), StockBalance.warehouse_id == warehouse_id
            )
        )
    }

    lines: list[PricedLine] = []
    for no, inp in enumerate(data.lines, start=1):
        item = items[inp.item_id]
        if not item.is_active:
            raise DomainError(f"کالای «{item.name}» غیرفعال است", code="item_inactive")
        unit_id = inp.unit_id or item.base_unit_id
        if unit_id == item.base_unit_id:
            factor = Decimal(1)
        elif (item.id, unit_id) in factors:
            factor = factors[(item.id, unit_id)]
        else:
            raise DomainError(f"واحد انتخاب‌شده برای «{item.name}» تعریف نشده است", code="bad_unit")
        qty = inp.qty
        source = "list"
        label_price: Decimal | None = None
        barcode = catalog.normalize_scan(inp.barcode) if inp.barcode else None
        if barcode and _is_scale_label(s, barcode):
            found = catalog.lookup(s, barcode, pl_id)
            if found.item_id != item.id:
                raise DomainError("برچسب ترازو با کالای ردیف مطابقت ندارد", code="label_mismatch")
            unit_id, factor, qty = item.base_unit_id, Decimal(1), found.qty
            if found.source == "scale_price" and found.line_price is not None:
                source, label_price = "scale", found.line_price
        unit_price = prices.get((item.id, unit_id))
        if unit_price is None:
            base = prices.get((item.id, item.base_unit_id))
            unit_price = rial(base * factor) if base is not None else None
        if label_price is not None:
            unit_price = unit_price or label_price
        if unit_price is None:
            raise DomainError(f"برای «{item.name}» قیمت فروش تعریف نشده است", code="no_price")
        if qty != qty.quantize(Decimal(1)) and not _fraction_ok(s, unit_id, item):
            raise DomainError(f"مقدار «{item.name}» باید عدد صحیح باشد", code="fraction_qty")
        gross = label_price if label_price is not None else rial(qty * unit_price)
        base_qty = (qty * factor).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

        best: Promotion | None = None
        best_amount = ZERO
        for p in promos:
            if p.item_id != item.id and (p.group_id is None or p.group_id != item.group_id):
                continue
            amount = (
                rial(gross * p.value / HUNDRED) if p.kind == "percent" else rial(p.value * base_qty)
            )
            amount = min(amount, gross)
            if amount > best_amount:
                best, best_amount = p, amount
        manual = rial(inp.manual_discount)
        if manual > gross - best_amount:
            raise DomainError(
                f"تخفیف «{item.name}» از مبلغ ردیف بیشتر است", code="discount_too_large"
            )
        rate = (
            ZERO
            if item.vat_exempt
            else (item.vat_rate if item.vat_rate is not None else org.default_vat_rate)
        )
        lines.append(
            PricedLine(
                line_no=no,
                item=item,
                unit_id=unit_id,
                unit_name=unit_names.get(unit_id, ""),
                factor=factor,
                qty=qty,
                base_qty=base_qty,
                unit_price=unit_price,
                price_source=source,
                gross=gross,
                promotion=best,
                promotion_discount=best_amount,
                manual_discount=manual,
                vat_exempt=item.vat_exempt,
                vat_rate=rate,
                stock_qty=stock.get(item.id, ZERO) if item.item_type == "goods" else None,
                scanned_barcode=barcode,
            )
        )

    # Invoice-level discount, spread in proportion to what is left of each line.
    invoice_discount = rial(data.discount)
    if invoice_discount:
        nets = [ln.gross - ln.promotion_discount - ln.manual_discount for ln in lines]
        total = sum(nets, ZERO)
        if invoice_discount > total:
            raise DomainError("تخفیف از مبلغ فاکتور بیشتر است", code="discount_too_large")
        left = invoice_discount
        for i, ln in enumerate(lines):
            share = left if i == len(lines) - 1 else rial(invoice_discount * nets[i] / total)
            share = min(share, nets[i], left)
            ln.manual_discount += share
            left -= share
        if left:  # rounding put the remainder past a line that was already exhausted
            for ln in lines:
                room = ln.gross - ln.promotion_discount - ln.manual_discount
                take = min(room, left)
                ln.manual_discount += take
                left -= take

    for ln in lines:
        net = ln.gross - ln.promotion_discount - ln.manual_discount
        if org.prices_include_vat:
            ln.tax = rial(net * ln.vat_rate / (HUNDRED + ln.vat_rate))
            ln.line_total, ln.revenue = net, net - ln.tax
        else:
            ln.tax = rial(net * ln.vat_rate / HUNDRED)
            ln.line_total, ln.revenue = net + ln.tax, net

    subtotal = sum((ln.gross for ln in lines), ZERO)
    manual_total = sum((ln.manual_discount for ln in lines), ZERO)
    percent = (manual_total * HUNDRED / subtotal).quantize(Decimal("0.01")) if subtotal else ZERO
    cart = PricedCart(
        lines=lines,
        subtotal=subtotal,
        promotion_total=sum((ln.promotion_discount for ln in lines), ZERO),
        manual_discount_total=manual_total,
        tax_total=sum((ln.tax for ln in lines), ZERO),
        grand_total=sum((ln.line_total for ln in lines), ZERO),
        manual_percent=percent,
        limit_percent=org.cashier_discount_limit,
    )

    wanted: dict[uuid.UUID, Decimal] = {}
    for ln in lines:
        if ln.item.item_type == "goods":
            wanted[ln.item.id] = wanted.get(ln.item.id, ZERO) + ln.base_qty
    for item_id, need in wanted.items():
        have = stock.get(item_id, ZERO)
        if need > have:
            name = items[item_id].name
            cart.short[item_id] = (name, have, need)
            if policy != "allow":
                cart.warnings.append(
                    f"موجودی «{name}» کافی نیست "
                    f"(موجود: {fmt_qty(have)}، در فاکتور: {fmt_qty(need)})"
                )
    return cart


def _fraction_ok(s: Session, unit_id: uuid.UUID, item: Item) -> bool:
    if item.is_weighted:
        return True
    unit = s.get(Unit, unit_id)
    return bool(unit and unit.allows_fraction)
