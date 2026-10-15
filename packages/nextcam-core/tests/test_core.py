from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import jdatetime
import pytest

from nextcam_core import CoreError
from nextcam_core.jalali import to_jalali
from nextcam_core.pricing import ItemRef, LineIn, PromoRef, Settings, price_cart
from nextcam_core.scan import LabelHit, ScaleRule, is_scale_label, normalize_scan, parse_scale

D = Decimal
PCS, PACK, KG = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
G = uuid.uuid4()


def item(code: str, **kw: object) -> ItemRef:
    base = dict(
        id=uuid.uuid4(),
        code=code,
        name=f"کالا {code}",
        group_id=None,
        base_unit_id=PCS,
        item_type="goods",
        is_active=True,
        is_weighted=False,
        vat_exempt=False,
        vat_rate=None,
    )
    base.update(kw)
    return ItemRef(**base)  # type: ignore[arg-type]


class Cat:
    def __init__(
        self,
        items: list[ItemRef],
        prices: dict,
        promos: list[PromoRef] | None = None,
        stock: dict | None = None,
        factors: dict | None = None,
        rules=None,
    ) -> None:
        self._items = {i.id: i for i in items}
        self._prices, self._promos = prices, promos or []
        self._stock, self._factors = stock or {}, factors or {}
        self.rules = rules or []

    def items(self, ids):
        return {i: self._items[i] for i in ids if i in self._items}

    def factor(self, item_id, unit_id):
        return self._factors.get((item_id, unit_id))

    def price(self, item_id, unit_id):
        return self._prices.get((item_id, unit_id))

    def unit_name(self, unit_id):
        return {PCS: "عدد", PACK: "بسته", KG: "کیلوگرم"}.get(unit_id, "")

    def unit_allows_fraction(self, unit_id):
        return unit_id == KG

    def stock(self, item_id):
        return self._stock.get(item_id, D(0))

    def promotions(self, item_ids, group_ids, today):
        return list(self._promos)

    def is_scale_label(self, code):
        return is_scale_label(code, self.rules)

    def scale_label(self, code) -> LabelHit:
        hit = parse_scale(
            code, self.rules, lambda plu: self._plu.get(plu), lambda i: self._prices.get((i, KG))
        )
        assert hit is not None
        return hit


VAT_EXCL = Settings(D(10), False, D(0), "warn")
VAT_INCL = Settings(D(10), True, D(5), "warn")


def test_jalali_matches_jdatetime_for_twenty_years() -> None:
    d = date(2015, 1, 1)
    while d < date(2035, 1, 1):
        j = jdatetime.date.fromgregorian(date=d)
        assert to_jalali(d) == (j.year, j.month, j.day), d
        d += timedelta(days=1)


def test_vat_exclusive_promotion_pack_and_invoice_discount() -> None:
    milk = item("M1", group_id=G)
    bread = item("B1", vat_exempt=True)
    cat = Cat(
        [milk, bread],
        {(milk.id, PCS): D(100000), (bread.id, PCS): D(50000)},
        promos=[PromoRef(uuid.uuid4(), "شیر ۱۰٪", "percent", D(10), None, G)],
        stock={milk.id: D(1)},
        factors={(milk.id, PACK): D(6)},
    )
    cart = price_cart(
        cat,
        VAT_EXCL,
        [LineIn(milk.id, D(1), unit_id=PACK), LineIn(bread.id, D(2))],
        D(10000),
        date(2026, 10, 1),
    )
    m, b = cart.lines
    assert (m.unit_price, m.gross, m.promotion_discount, m.base_qty) == (
        D(600000),
        D(600000),
        D(60000),
        D("6.000"),
    )
    # 10 000 invoice discount spread 540 000 : 100 000 → 8 438 + rest.
    assert m.manual_discount + b.manual_discount == D(10000)
    assert m.tax == ((m.gross - m.promotion_discount - m.manual_discount) * D("0.1")).quantize(D(1))
    assert b.tax == 0 and b.vat_rate == 0
    assert cart.grand_total == sum((ln.line_total for ln in cart.lines), D(0))
    assert cart.short[milk.id][1:] == (D(1), D("6.000")) and len(cart.warnings) == 2


def test_vat_inclusive_and_errors() -> None:
    milk = item("M1")
    cat = Cat([milk], {(milk.id, PCS): D(110000)})
    cart = price_cart(cat, VAT_INCL, [LineIn(milk.id, D(1))], D(0), date(2026, 10, 1))
    ln = cart.lines[0]
    assert (ln.tax, ln.revenue, ln.line_total) == (D(10000), D(100000), D(110000))
    with pytest.raises(CoreError) as e:
        price_cart(cat, VAT_INCL, [LineIn(milk.id, D("1.5"))], D(0), date(2026, 10, 1))
    assert e.value.code == "fraction_qty"
    with pytest.raises(CoreError) as e:
        price_cart(cat, VAT_INCL, [LineIn(uuid.uuid4(), D(1))], D(0), date(2026, 10, 1))
    assert e.value.not_found
    with pytest.raises(CoreError) as e:
        price_cart(
            cat,
            VAT_INCL,
            [LineIn(milk.id, D(1), manual_discount=D(200000))],
            D(0),
            date(2026, 10, 1),
        )
    assert e.value.code == "discount_too_large"


def test_scale_labels_are_read_from_the_barcode() -> None:
    cheese = item("CH", base_unit_id=KG, is_weighted=True)
    rules = [ScaleRule("21", 5, "weight", 3)]
    cat = Cat([cheese], {(cheese.id, KG): D(3900000)}, rules=rules)
    cat._plu = {"00201": cheese.id}  # type: ignore[attr-defined]
    code12 = "210020101250"  # PLU 00201, 1.250 kg
    from nextcam_core.scan import ean13_check_digit

    code = code12 + str(ean13_check_digit(code12))
    cart = price_cart(
        cat, VAT_EXCL, [LineIn(cheese.id, D(9), barcode=code)], D(0), date(2026, 10, 1)
    )
    assert (cart.lines[0].qty, cart.lines[0].gross) == (D("1.250"), D(4875000))
    with pytest.raises(CoreError) as e:
        parse_scale(
            code12 + "0" if code[-1] != "0" else code12 + "1", rules, lambda p: None, lambda i: None
        )
    assert e.value.code == "bad_check_digit"
    assert normalize_scan(" ۶۲۶۰ ") == "6260"
