"""Cart pricing: list price, scale labels, promotions, manual and invoice discounts, VAT.

The single implementation of ADR-0013 §2–3: the server runs it on SQL Server data
(`sales.services.pricing`) and the register agent on its offline snapshot. Amounts
are whole rials; all arithmetic is Decimal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from nextcam_core import CoreError
from nextcam_core.scan import LabelHit, normalize_scan

ZERO = Decimal(0)
RIAL = Decimal(1)
HUNDRED = Decimal(100)


def rial(d: Decimal) -> Decimal:
    return d.quantize(RIAL, rounding=ROUND_HALF_UP)


def fmt_qty(d: Decimal) -> str:
    return format(d.normalize(), "f")


@dataclass(frozen=True)
class ItemRef:
    id: uuid.UUID
    code: str
    name: str
    group_id: uuid.UUID | None
    base_unit_id: uuid.UUID
    item_type: str
    is_active: bool
    is_weighted: bool
    vat_exempt: bool
    vat_rate: Decimal | None


@dataclass(frozen=True)
class PromoRef:
    id: uuid.UUID
    name: str
    kind: str  # "percent" | "amount" (per base unit)
    value: Decimal
    item_id: uuid.UUID | None
    group_id: uuid.UUID | None


@dataclass(frozen=True)
class Settings:
    default_vat_rate: Decimal
    prices_include_vat: bool
    cashier_discount_limit: Decimal
    negative_stock_policy: str


@dataclass(frozen=True)
class LineIn:
    item_id: uuid.UUID
    qty: Decimal
    unit_id: uuid.UUID | None = None
    barcode: str | None = None
    manual_discount: Decimal = ZERO


class Catalog(Protocol):
    """What pricing needs to know; the server reads SQL Server, the agent its cache."""

    def items(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, ItemRef]: ...
    def factor(self, item_id: uuid.UUID, unit_id: uuid.UUID) -> Decimal | None: ...
    def price(self, item_id: uuid.UUID, unit_id: uuid.UUID) -> Decimal | None: ...
    def unit_name(self, unit_id: uuid.UUID) -> str: ...
    def unit_allows_fraction(self, unit_id: uuid.UUID) -> bool: ...
    def stock(self, item_id: uuid.UUID) -> Decimal: ...
    def promotions(
        self, item_ids: list[uuid.UUID], group_ids: list[uuid.UUID], today: date
    ) -> list[PromoRef]: ...
    def is_scale_label(self, code: str) -> bool: ...
    def scale_label(self, code: str) -> LabelHit: ...


@dataclass
class PricedLine:
    line_no: int
    item: ItemRef
    unit_id: uuid.UUID
    unit_name: str
    factor: Decimal
    qty: Decimal
    base_qty: Decimal
    unit_price: Decimal
    price_source: str
    gross: Decimal
    promotion: PromoRef | None
    promotion_discount: Decimal
    manual_discount: Decimal
    vat_exempt: bool
    vat_rate: Decimal
    tax: Decimal = ZERO
    revenue: Decimal = ZERO
    line_total: Decimal = ZERO
    stock_qty: Decimal | None = None
    scanned_barcode: str | None = None


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


def price_cart(
    cat: Catalog,
    settings: Settings,
    lines_in: list[LineIn],
    discount: Decimal,
    today: date,
    negative_policy: str | None = None,
) -> PricedCart:
    policy = negative_policy or settings.negative_stock_policy
    ids = list(dict.fromkeys(inp.item_id for inp in lines_in))
    items = cat.items(ids)
    for inp in lines_in:
        if inp.item_id not in items:
            raise CoreError("کالا یافت نشد", "not_found", not_found=True)
    group_ids = [i.group_id for i in items.values() if i.group_id]
    promos = cat.promotions(ids, group_ids, today)

    lines: list[PricedLine] = []
    for no, inp in enumerate(lines_in, start=1):
        item = items[inp.item_id]
        if not item.is_active:
            raise CoreError(f"کالای «{item.name}» غیرفعال است", "item_inactive")
        unit_id = inp.unit_id or item.base_unit_id
        if unit_id == item.base_unit_id:
            factor = Decimal(1)
        else:
            f = cat.factor(item.id, unit_id)
            if f is None:
                raise CoreError(f"واحد انتخاب‌شده برای «{item.name}» تعریف نشده است", "bad_unit")
            factor = f
        qty = inp.qty
        source = "list"
        label_price: Decimal | None = None
        barcode = normalize_scan(inp.barcode) if inp.barcode else None
        if barcode and cat.is_scale_label(barcode):
            found = cat.scale_label(barcode)
            if found.item_id != item.id:
                raise CoreError("برچسب ترازو با کالای ردیف مطابقت ندارد", "label_mismatch")
            unit_id, factor, qty = item.base_unit_id, Decimal(1), found.qty
            if found.source == "scale_price" and found.line_price is not None:
                source, label_price = "scale", found.line_price
        unit_price = cat.price(item.id, unit_id)
        if unit_price is None:
            base = cat.price(item.id, item.base_unit_id)
            unit_price = rial(base * factor) if base is not None else None
        if label_price is not None:
            unit_price = unit_price or label_price
        if unit_price is None:
            raise CoreError(f"برای «{item.name}» قیمت فروش تعریف نشده است", "no_price")
        if (
            qty != qty.quantize(Decimal(1))
            and not item.is_weighted
            and not cat.unit_allows_fraction(unit_id)
        ):
            raise CoreError(f"مقدار «{item.name}» باید عدد صحیح باشد", "fraction_qty")
        gross = label_price if label_price is not None else rial(qty * unit_price)
        base_qty = (qty * factor).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

        best: PromoRef | None = None
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
            raise CoreError(f"تخفیف «{item.name}» از مبلغ ردیف بیشتر است", "discount_too_large")
        rate = (
            ZERO
            if item.vat_exempt
            else (item.vat_rate if item.vat_rate is not None else settings.default_vat_rate)
        )
        lines.append(
            PricedLine(
                line_no=no,
                item=item,
                unit_id=unit_id,
                unit_name=cat.unit_name(unit_id),
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
                stock_qty=cat.stock(item.id) if item.item_type == "goods" else None,
                scanned_barcode=barcode,
            )
        )

    # Invoice-level discount, spread in proportion to what is left of each line.
    invoice_discount = rial(discount)
    if invoice_discount:
        nets = [ln.gross - ln.promotion_discount - ln.manual_discount for ln in lines]
        total = sum(nets, ZERO)
        if invoice_discount > total:
            raise CoreError("تخفیف از مبلغ فاکتور بیشتر است", "discount_too_large")
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
        if settings.prices_include_vat:
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
        limit_percent=settings.cashier_discount_limit,
    )

    wanted: dict[uuid.UUID, Decimal] = {}
    for ln in lines:
        if ln.item.item_type == "goods":
            wanted[ln.item.id] = wanted.get(ln.item.id, ZERO) + ln.base_qty
    for item_id, need in wanted.items():
        have = cat.stock(item_id)
        if need > have:
            name = items[item_id].name
            cart.short[item_id] = (name, have, need)
            if policy != "allow":
                cart.warnings.append(
                    f"موجودی «{name}» کافی نیست "
                    f"(موجود: {fmt_qty(have)}، در فاکتور: {fmt_qty(need)})"
                )
    return cart
