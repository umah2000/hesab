"""Receipt print payload: everything formatted here (Persian digits, toman/rial, Jalali
date), so the printer side only lays text out and never decides amounts.

Same content as the browser receipt (frontend ``Receipt.tsx``). Used by the server for
online receipts and by the register agent for offline ones (device number instead of
the final number).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from nextcam_core.jalali import to_jalali

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
METHOD = {"cash": "نقد", "card": "کارت", "credit": "نسیه"}


def fa(v: object) -> str:
    return str(v).translate(FA_DIGITS)


def money(rials: Decimal, currency: str) -> str:
    """Grouped amount in the display currency, Persian digits (e.g. ۱۱۰٬۰۰۰)."""
    v = rials / 10 if currency == "IRT" else rials
    v = v.quantize(Decimal("0.1")) if v != v.to_integral_value() else v.quantize(Decimal(1))
    sign = "−" if v < 0 else ""
    whole, _, frac = f"{abs(v):f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", "٬")
    return sign + fa(grouped + (f"٫{frac}" if frac else ""))


def qty(v: Decimal) -> str:
    s = f"{v.normalize():f}"
    return fa(s.replace(".", "٫"))


def jalali(dt: datetime, tz: str) -> str:
    local = dt.astimezone(ZoneInfo(tz))
    jy, jm, jd = to_jalali(local.date())
    return fa(f"{jy:04d}/{jm:02d}/{jd:02d}  {local:%H:%M}")


def build(
    inv: Any,
    *,
    organization: str,
    header: str | None,
    footer: str | None,
    currency: str,
    timezone: str,
    reprint: bool,
    open_drawer: bool,
    cut: bool,
    device_number: str | None = None,
) -> dict[str, Any]:
    """``inv`` is a final invoice (server ``InvoiceOut``) or an offline sale with the same
    attribute names. Offline sales have no final number yet: the device number is shown."""
    is_return = inv.kind == "return"

    def m(d: Decimal) -> str:
        return money(d, currency)

    meta = [
        # A register number is a code staff type into search: kept in Latin characters.
        ["شماره", fa(inv.number or 0)] if not device_number else ["شماره صندوق", device_number],
        ["تاریخ", jalali(inv.finalized_at or inv.created_at, timezone)],
        ["صندوق", inv.register_name],
        ["صندوق‌دار", inv.cashier_name],
    ]
    if is_return and inv.original_number:
        meta.append(["برگشت فاکتور", fa(inv.original_number)])
    if inv.customer_name:
        meta.append(["مشتری", inv.customer_name])
    lines = []
    for ln in inv.lines:
        detail = f"{qty(ln.qty)} {ln.unit_name} × {m(ln.unit_price)}"
        disc = ln.promotion_discount + ln.manual_discount
        if disc:
            detail += f" − تخفیف {m(disc)}"
        lines.append(
            {
                "name": ln.item_name + (" *" if ln.vat_exempt else ""),
                "detail": detail,
                "amount": m(ln.line_total),
            }
        )
    totals: list[dict[str, Any]] = [{"label": "جمع", "value": m(inv.subtotal), "bold": False}]
    if inv.discount_total:
        totals.append({"label": "تخفیف", "value": m(inv.discount_total), "bold": False})
    totals.append({"label": "مالیات بر ارزش افزوده", "value": m(inv.tax_total), "bold": False})
    unit = "تومان" if currency == "IRT" else "ریال"
    totals.append(
        {
            "label": "مبلغ استرداد" if is_return else "قابل پرداخت",
            "value": f"{m(inv.grand_total)} {unit}",
            "bold": True,
        }
    )
    for p in inv.payments:
        label = METHOD[p.method] + (f" (پیگیری {fa(p.card_reference)})" if p.card_reference else "")
        totals.append({"label": label, "value": m(p.amount), "bold": False})
    if inv.cash_tendered:
        totals.append({"label": "دریافتی", "value": m(inv.cash_tendered), "bold": False})
    if inv.change_due:
        totals.append({"label": "باقی‌مانده", "value": m(inv.change_due), "bold": False})
    notes = ["* کالای معاف از مالیات"] if any(ln.vat_exempt for ln in inv.lines) else []
    if device_number:
        notes.append("ثبت در حالت آفلاین؛ شماره قطعی پس از اتصال به سرور داده می‌شود.")
    return {
        "title": organization,
        "header": (header or "").splitlines(),
        "heading": ("رسید برگشت از فروش" if is_return else "فاکتور فروش")
        + (" (چاپ مجدد)" if reprint else ""),
        "meta": meta,
        "lines": lines,
        "totals": totals,
        "notes": notes,
        "footer": (footer or "").splitlines(),
        "open_drawer": open_drawer,
        "cut": cut,
    }


def test_page(name: str, width: int) -> dict[str, Any]:
    return {
        "title": "NEXTCAM",
        "header": [],
        "heading": "صفحه آزمایشی چاپگر",
        "meta": [["دستگاه", name], ["عرض کاغذ", fa(f"{width} میلی‌متر")]],
        "lines": [
            {"name": "متن فارسی و English 0123456789", "detail": "۰۱۲۳۴۵۶۷۸۹", "amount": "۱۲۳٬۴۵۶"}
        ],
        "totals": [{"label": "جمع آزمایشی", "value": "۱۲۳٬۴۵۶ تومان", "bold": True}],
        "notes": ["اگر این متن خوانا و راست‌چین است، چاپگر درست تنظیم شده."],
        "footer": [],
        "open_drawer": False,
        "cut": True,
    }
