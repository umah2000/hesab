"""Barcode normalisation and scale-label decoding (weight or price in the barcode).

A scale label is [prefix][PLU][value] = 12 digits, then an EAN-13 check digit, or, on
scales that print a plain 12-digit code (Code 128 and the like), no check digit."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from nextcam_core import CoreError

# A scanner typing through a Persian keyboard layout: digits and letters back to Latin.
_FA_LAYOUT = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩ضصثقفغعهخحجچشسیبلاتنمکگظطزرذدپوئ",
    "01234567890123456789qwertyuiop[]asdfghjkl;'zxcvbnm,.",
)
MONEY_PLACES = Decimal("0.0001")


def normalize_scan(raw: str) -> str:
    return raw.strip().translate(_FA_LAYOUT).upper().replace(" ", "")


def ean13_check_digit(first12: str) -> int:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return (10 - total % 10) % 10


@dataclass(frozen=True)
class ScaleRule:
    prefix: str
    item_code_length: int
    value_type: str  # "weight" | "price"
    value_decimals: int
    check_digit: bool = True  # False: the scale prints 12 digits, no EAN check digit

    @property
    def length(self) -> int:
        return 13 if self.check_digit else 12

    def matches(self, code: str) -> bool:
        return len(code) == self.length and code.isdigit() and code.startswith(self.prefix)


@dataclass(frozen=True)
class LabelHit:
    item_id: uuid.UUID
    qty: Decimal
    source: str  # "scale_weight" | "scale_price"
    line_price: Decimal | None


def is_scale_label(code: str, rules: list[ScaleRule]) -> bool:
    return any(r.matches(code) for r in rules)


def parse_scale(
    code: str,
    rules: list[ScaleRule],
    find_plu: Callable[[str], uuid.UUID | None],
    unit_price: Callable[[uuid.UUID], Decimal | None],
) -> LabelHit | None:
    """Decode a scale label; None if no rule's prefix matches. The weight or price is
    always read from the label itself, never from what the client sent."""
    for rule in rules:
        if not rule.matches(code):
            continue
        if rule.check_digit and ean13_check_digit(code[:12]) != int(code[12]):
            raise CoreError("رقم کنترل بارکد ترازو نادرست است؛ دوباره اسکن کنید", "bad_check_digit")
        start = len(rule.prefix)
        plu = code[start : start + rule.item_code_length]
        value = Decimal(code[start + rule.item_code_length : 12])
        item_id = find_plu(plu)
        if item_id is None:
            raise CoreError(f"کالایی با کد ترازو {plu} تعریف نشده است", "not_found", not_found=True)
        scale = Decimal(10) ** rule.value_decimals
        if rule.value_type == "weight":
            qty = (value / scale).quantize(Decimal("0.001"))
            if qty <= 0:
                raise CoreError("وزن برچسب صفر است", "zero_weight")
            return LabelHit(item_id, qty, "scale_weight", None)
        price = (value * scale).quantize(MONEY_PLACES)  # label price → rials
        up = unit_price(item_id)
        qty = (price / up).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP) if up else Decimal(1)
        return LabelHit(item_id, qty, "scale_price", price)
    return None
