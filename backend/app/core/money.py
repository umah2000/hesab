"""Money and quantity types (ADR-0008).

Amounts travel as JSON strings and are Decimal everywhere. A JSON number is
rejected, because a float such as 0.1 has already lost precision by the time
it reaches us.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer

MONEY_PLACES = Decimal("0.0001")
QTY_PLACES = Decimal("0.001")
# DECIMAL(19,4): 15 integer digits.
MAX_MONEY = Decimal("999999999999999.9999")

_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def parse_decimal(value: Any, places: Decimal = MONEY_PLACES) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ValueError("مبلغ باید به‌صورت رشته ارسال شود، نه عدد اعشاری")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        cleaned = value.strip().translate(_FA).replace(",", "").replace("٬", "").replace("٫", ".")
        try:
            d = Decimal(cleaned)
        except InvalidOperation as e:
            raise ValueError("مبلغ نامعتبر است") from e
    else:
        raise ValueError("مبلغ نامعتبر است")
    if not d.is_finite():
        raise ValueError("مبلغ نامعتبر است")
    if abs(d) > MAX_MONEY:
        raise ValueError("مبلغ بیش از حد مجاز است")
    if d != d.quantize(places):
        raise ValueError(f"حداکثر {len(str(places).split('.')[1])} رقم اعشار مجاز است")
    return d.quantize(places)


def round_money(d: Decimal) -> Decimal:
    return d.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def _money_str(d: Decimal) -> str:
    return format(d.quantize(MONEY_PLACES), "f")


Money = Annotated[
    Decimal,
    BeforeValidator(parse_decimal),
    PlainSerializer(_money_str, return_type=str, when_used="json"),
]

ZERO = Decimal("0.0000")
