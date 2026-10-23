"""Selling without the server: the register's own catalogue, pricing and sales queue.

Pricing is ``nextcam_core.pricing`` — the very code the server runs — on the snapshot
the server sent (ADR-0017). Responses keep the server's shapes, so the POS shows an
offline sale like any other; it only gets the register's number instead of the final
one. What needs the server is refused here: credit sales (balances), customers,
returns, held carts, supervisor approvals, card-reader integration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from nextcam_core import CoreError
from nextcam_core.pricing import (
    ItemRef,
    LineIn,
    PricedCart,
    PromoRef,
    Settings,
    price_cart,
    rial,
)
from nextcam_core.receipt import build as build_receipt
from nextcam_core.scan import LabelHit, ScaleRule, is_scale_label, normalize_scan, parse_scale

from nextcam_agent.store import Store

# Iran has kept UTC+03:30 all year since 2022; the business date only.
TEHRAN = timezone(timedelta(hours=3, minutes=30))
ZERO = Decimal(0)
MONEY = Decimal("0.0001")
QTY = Decimal("0.001")
# What a cashier may still do offline (from the shift's permissions).
OFFLINE_PERMISSIONS = frozenset(
    {
        "sales.pos.use",
        "sales.payment.cash",
        "sales.payment.card",
        "sales.invoice.discount",
        "sales.invoice.discount_over_limit",
        "sales.invoice.line_delete_after_scan",
    }
)


class OfflineError(Exception):
    def __init__(self, message: str, code: str, status: int = 422) -> None:
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def m(d: Decimal) -> str:
    return format(d.quantize(MONEY), "f")


def q3(d: Decimal) -> str:
    return format(d.quantize(QTY), "f")


def plain(d: Decimal) -> str:
    return format(d.normalize(), "f")


def dec(v: Any, what: str, places: Decimal = MONEY) -> Decimal:
    """Amounts arrive as strings (never JSON floats), like on the server."""
    if isinstance(v, (bool, float)) or v is None:
        raise OfflineError(f"{what} نامعتبر است", "validation_error", 400)
    try:
        d = Decimal(str(v).strip().replace(",", ""))
    except InvalidOperation as e:
        raise OfflineError(f"{what} نامعتبر است", "validation_error", 400) from e
    if not d.is_finite():
        raise OfflineError(f"{what} نامعتبر است", "validation_error", 400)
    return d.quantize(places)


def uid(v: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(v)))
    except ValueError as e:
        raise OfflineError(f"{what} نامعتبر است", "validation_error", 400) from e


def business_date(at: datetime | None = None) -> date:
    return (at or datetime.now(UTC)).astimezone(TEHRAN).date()


# --- snapshot --------------------------------------------------------------------


def _d(v: str | None) -> Decimal | None:
    return None if v is None else Decimal(v)


@dataclass
class Snapshot:
    """The server's snapshot, indexed for scanning, plus what was sold here since."""

    raw: dict[str, Any]
    fetched_at: str | None

    def __post_init__(self) -> None:
        r = self.raw
        self.version: str = r["version"]
        self.valid_until = datetime.fromisoformat(r["valid_until"])
        self.register: dict[str, Any] = r["cash_register"]
        self.shift: dict[str, Any] | None = r["shift"]
        self.settings: dict[str, Any] = r["settings"]
        self.prefix: str = r["number_prefix"]
        self.items: dict[str, dict[str, Any]] = {i["id"]: i for i in r["items"]}
        self.units: dict[str, dict[str, Any]] = {u["id"]: u for u in r["units"]}
        self.factors = {(f["item_id"], f["unit_id"]): Decimal(f["factor"]) for f in r["factors"]}
        self.prices = {(p["item_id"], p["unit_id"]): Decimal(p["price"]) for p in r["prices"]}
        self.barcodes: dict[str, dict[str, Any]] = {b["barcode"]: b for b in r["barcodes"]}
        self.by_scale_code: dict[str, str] = {}
        for i in r["items"]:
            if i.get("scale_code"):
                self.by_scale_code[i["scale_code"]] = i["id"]
                self.by_scale_code[i["scale_code"].lstrip("0")] = i["id"]
        self.by_code: dict[str, str] = {i["code"].upper(): i["id"] for i in r["items"]}
        self.rules = [
            ScaleRule(
                x["prefix"],
                x["item_code_length"],
                x["value_type"],
                x["value_decimals"],
                x.get("check_digit", True),
            )
            for x in r["scale_rules"]
        ]
        self.promos: list[dict[str, Any]] = r["promotions"]
        self.sold: dict[str, Decimal] = {}

    def with_unsettled(self, unsettled: dict[str, list[str]]) -> Snapshot:
        self.sold = {k: sum((Decimal(x) for x in v), ZERO) for k, v in unsettled.items()}
        return self

    def valid(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) < self.valid_until

    def core_settings(self) -> Settings:
        s = self.settings
        return Settings(
            default_vat_rate=Decimal(s["default_vat_rate"]),
            prices_include_vat=bool(s["prices_include_vat"]),
            cashier_discount_limit=Decimal(s["cashier_discount_limit"]),
            negative_stock_policy=s["negative_stock_policy"],
        )

    def stock(self, item_id: str) -> Decimal:
        i = self.items.get(item_id)
        base = _d(i["stock"]) if i and i.get("stock") is not None else ZERO
        return (base or ZERO) - self.sold.get(item_id, ZERO)

    def price_of(self, item_id: str, unit_id: str) -> Decimal | None:
        """The unit's price; without one, the base price times the unit's factor."""
        if (item_id, unit_id) in self.prices:
            return self.prices[(item_id, unit_id)]
        item = self.items[item_id]
        base = self.prices.get((item_id, item["base_unit_id"]))
        if base is None or unit_id == item["base_unit_id"]:
            return base
        f = self.factors.get((item_id, unit_id))
        return rial(base * f) if f is not None else None


class SnapCatalog:
    """``nextcam_core.pricing.Catalog`` over the snapshot."""

    def __init__(self, snap: Snapshot) -> None:
        self.snap = snap

    def items(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, ItemRef]:
        out = {}
        for i in ids:
            raw = self.snap.items.get(str(i))
            if raw is not None:
                out[i] = ItemRef(
                    id=i,
                    code=raw["code"],
                    name=raw["name"],
                    group_id=uuid.UUID(raw["group_id"]) if raw["group_id"] else None,
                    base_unit_id=uuid.UUID(raw["base_unit_id"]),
                    item_type=raw["item_type"],
                    is_active=True,  # the snapshot holds active items only
                    is_weighted=raw["is_weighted"],
                    vat_exempt=raw["vat_exempt"],
                    vat_rate=_d(raw["vat_rate"]),
                )
        return out

    def factor(self, item_id: uuid.UUID, unit_id: uuid.UUID) -> Decimal | None:
        return self.snap.factors.get((str(item_id), str(unit_id)))

    def price(self, item_id: uuid.UUID, unit_id: uuid.UUID) -> Decimal | None:
        return self.snap.prices.get((str(item_id), str(unit_id)))

    def unit_name(self, unit_id: uuid.UUID) -> str:
        u = self.snap.units.get(str(unit_id))
        return u["name"] if u else ""

    def unit_allows_fraction(self, unit_id: uuid.UUID) -> bool:
        u = self.snap.units.get(str(unit_id))
        return bool(u and u["allows_fraction"])

    def stock(self, item_id: uuid.UUID) -> Decimal:
        return self.snap.stock(str(item_id))

    def promotions(
        self, item_ids: list[uuid.UUID], group_ids: list[uuid.UUID], today: date
    ) -> list[PromoRef]:
        items, groups, day = {str(i) for i in item_ids}, {str(g) for g in group_ids}, str(today)
        return [
            PromoRef(
                uuid.UUID(p["id"]),
                p["name"],
                p["kind"],
                Decimal(p["value"]),
                uuid.UUID(p["item_id"]) if p["item_id"] else None,
                uuid.UUID(p["group_id"]) if p["group_id"] else None,
            )
            for p in self.snap.promos
            if p["starts_on"] <= day <= p["ends_on"]
            and (p["item_id"] in items or p["group_id"] in groups)
        ]

    def is_scale_label(self, code: str) -> bool:
        return is_scale_label(code, self.snap.rules)

    def scale_label(self, code: str) -> LabelHit:
        hit = self._parse(code)
        if hit is None:
            raise CoreError("برچسب ترازو شناخته نشد", "not_found", not_found=True)
        return hit

    def _parse(self, code: str) -> LabelHit | None:
        snap = self.snap

        def find_plu(plu: str) -> uuid.UUID | None:
            found = snap.by_scale_code.get(plu) or snap.by_scale_code.get(plu.lstrip("0"))
            return uuid.UUID(found) if found else None

        def base_price(item_id: uuid.UUID) -> Decimal | None:
            i = snap.items.get(str(item_id))
            return snap.price_of(str(item_id), i["base_unit_id"]) if i else None

        return parse_scale(code, snap.rules, find_plu, base_price)


def _core(e: CoreError) -> OfflineError:
    return OfflineError(e.message, e.code, 404 if e.not_found else 422)


# --- scanning and search -----------------------------------------------------------


def lookup(snap: Snapshot, raw: str) -> dict[str, Any]:
    """Same answer as the server's /inventory/items/lookup."""
    code = normalize_scan(raw)
    if not code:
        raise OfflineError("بارکد خالی است", "empty_barcode")

    def result(
        item_id: str, unit_id: str, qty: Decimal, source: str, line_price: Decimal | None = None
    ) -> dict[str, Any]:
        item = snap.items[item_id]
        unit_price = snap.price_of(item_id, unit_id)
        if line_price is None and unit_price is not None:
            line_price = rial(unit_price * qty)
        unit = snap.units.get(unit_id)
        return {
            "item_id": item_id,
            "code": item["code"],
            "name": item["name"],
            "unit_id": unit_id,
            "unit_name": unit["name"] if unit else "",
            "qty": q3(qty),
            "unit_price": m(unit_price) if unit_price is not None else None,
            "line_price": m(line_price) if line_price is not None else None,
            "source": source,
            "is_weighted": item["is_weighted"],
            "vat_exempt": item["vat_exempt"],
            "vat_rate": item["vat_rate"],
        }

    bc = snap.barcodes.get(code)
    if bc and bc["item_id"] in snap.items:
        unit = bc["unit_id"] or snap.items[bc["item_id"]]["base_unit_id"]
        return result(
            bc["item_id"], unit, Decimal(1), "pack_barcode" if bc["unit_id"] else "barcode"
        )
    if is_scale_label(code, snap.rules):
        try:
            hit = SnapCatalog(snap)._parse(code)
        except CoreError as e:
            raise _core(e) from e
        if hit is not None:
            item_id = str(hit.item_id)
            return result(
                item_id,
                snap.items[item_id]["base_unit_id"],
                hit.qty,
                hit.source,
                hit.line_price,
            )
    by_code = snap.by_code.get(code)
    if by_code:
        return result(by_code, snap.items[by_code]["base_unit_id"], Decimal(1), "code")
    raise OfflineError(f"کالایی با بارکد {code} یافت نشد", "not_found", 404)


def search(snap: Snapshot, text: str, page_size: int = 12) -> dict[str, Any]:
    """Same shape as the server's /inventory/items (code, name or barcode)."""
    needle = text.strip().lower()
    barcode_items = {b["item_id"]: code for code, b in snap.barcodes.items()}
    hits = []
    for i in snap.items.values():
        code, name = i["code"].lower(), i["name"].lower()
        if not needle:
            rank = 3
        elif code == needle:
            rank = 0
        elif code.startswith(needle) or name.startswith(needle):
            rank = 1
        elif needle in name or needle in code or needle == barcode_items.get(i["id"], "").lower():
            rank = 2
        else:
            continue
        hits.append((rank, i["name"], i))
    hits.sort(key=lambda h: (h[0], h[1]))
    out = []
    for _, _, i in hits[:page_size]:
        unit = snap.units.get(i["base_unit_id"])
        price = snap.price_of(i["id"], i["base_unit_id"])
        out.append(
            {
                "id": i["id"],
                "code": i["code"],
                "name": i["name"],
                "group_name": None,
                "base_unit_name": unit["name"] if unit else "",
                "is_weighted": i["is_weighted"],
                "is_active": True,
                "barcode": barcode_items.get(i["id"]),
                "price": m(price) if price is not None else None,
                "stock_qty": q3(snap.stock(i["id"])),
            }
        )
    return {"items": out, "total": len(hits), "page": 1, "page_size": page_size}


# --- quote ---------------------------------------------------------------------------


def _lines(body: dict[str, Any]) -> tuple[list[LineIn], Decimal]:
    raw = body.get("lines")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 500:
        raise OfflineError("ردیف‌های فاکتور نامعتبر است", "validation_error", 400)
    lines = []
    for ln in raw:
        if not isinstance(ln, dict):
            raise OfflineError("ردیف نامعتبر است", "validation_error", 400)
        qty = dec(ln.get("qty"), "مقدار", QTY)
        disc = dec(ln.get("manual_discount", "0"), "تخفیف")
        if qty <= 0 or disc < 0:
            raise OfflineError("مقدار یا تخفیف نامعتبر است", "validation_error", 400)
        barcode = ln.get("barcode")
        lines.append(
            LineIn(
                item_id=uuid.UUID(uid(ln.get("item_id"), "کالا")),
                qty=qty,
                unit_id=uuid.UUID(uid(ln["unit_id"], "واحد")) if ln.get("unit_id") else None,
                barcode=str(barcode)[:48] if barcode else None,
                manual_discount=disc,
            )
        )
    discount = dec(body.get("discount", "0"), "تخفیف")
    if discount < 0:
        raise OfflineError("تخفیف نامعتبر است", "validation_error", 400)
    return lines, discount


def price(snap: Snapshot, body: dict[str, Any], today: date | None = None) -> PricedCart:
    lines, discount = _lines(body)
    try:
        return price_cart(
            SnapCatalog(snap), snap.core_settings(), lines, discount, today or business_date()
        )
    except CoreError as e:
        raise _core(e) from e


def quote_view(cart: PricedCart) -> dict[str, Any]:
    return {
        "lines": [line_view(ln) for ln in cart.lines],
        "subtotal": m(cart.subtotal),
        "promotion_total": m(cart.promotion_total),
        "manual_discount_total": m(cart.manual_discount_total),
        "discount_total": m(cart.discount_total),
        "tax_total": m(cart.tax_total),
        "grand_total": m(cart.grand_total),
        "manual_discount_percent": plain(cart.manual_percent),
        "discount_limit_percent": plain(cart.limit_percent),
        "needs_discount_approval": cart.needs_discount_approval,
        "warnings": cart.warnings,
    }


def line_view(ln: Any) -> dict[str, Any]:
    # As the server's QuoteLineOut: the receipt's shop price and amount, before tax.
    net = ln.gross - ln.promotion_discount - ln.manual_discount
    net_unit = (
        (net / ln.qty).quantize(Decimal(1), rounding=ROUND_HALF_UP) if ln.qty else ln.unit_price
    )
    return {
        "line_no": ln.line_no,
        "item_id": str(ln.item.id),
        "item_code": ln.item.code,
        "item_name": ln.item.name,
        "unit_id": str(ln.unit_id),
        "unit_name": ln.unit_name,
        "qty": q3(ln.qty),
        "unit_price": m(ln.unit_price),
        "price_source": ln.price_source,
        "gross": m(ln.gross),
        "promotion_id": str(ln.promotion.id) if ln.promotion else None,
        "promotion_name": ln.promotion.name if ln.promotion else None,
        "promotion_discount": m(ln.promotion_discount),
        "manual_discount": m(ln.manual_discount),
        "vat_exempt": ln.vat_exempt,
        "vat_rate": plain(ln.vat_rate),
        "tax": m(ln.tax),
        "line_total": m(ln.line_total),
        "stock_qty": q3(ln.stock_qty) if ln.stock_qty is not None else None,
        "scanned_barcode": ln.scanned_barcode,
        "net_amount": m(net),
        "net_unit_price": m(net_unit),
    }


# --- state ---------------------------------------------------------------------------


def permissions(snap: Snapshot) -> list[str]:
    return sorted(OFFLINE_PERMISSIONS & set(snap.shift["permissions"] if snap.shift else []))


def shift_view(snap: Snapshot) -> dict[str, Any] | None:
    sh, reg = snap.shift, snap.register
    if sh is None:
        return None
    return {
        "id": sh["id"],
        "branch_id": reg["branch_id"],
        "cash_register_id": reg["id"],
        "register_name": reg["name"],
        "user_id": sh["user_id"],
        "user_name": sh["user_name"],
        "status": "open",
        "opened_at": sh["opened_at"],
        "opening_cash": sh["opening_cash"],
        "closed_at": None,
        "expected_cash": None,
        "counted_cash": None,
        "difference": None,
        "close_note": None,
        "voucher_id": None,
        "row_version": "",
    }


def register_state(snap: Snapshot) -> dict[str, Any]:
    reg, st = snap.register, snap.settings
    return {
        "cash_register_id": reg["id"],
        "register_name": reg["name"],
        "branch_id": reg["branch_id"],
        "branch_name": reg["branch_name"],
        "warehouse_id": reg["warehouse_id"],
        "shift": shift_view(snap),
        "other_shift_user": None,
        "held_count": 0,
        "display_currency": st["display_currency"],
        "receipt_header": st["receipt_header"],
        "receipt_footer": st["receipt_footer"],
        "organization_name": st["organization_name"],
        "terminal": None,
        "permissions": permissions(snap),
    }


# --- sale ------------------------------------------------------------------------------


def _payments(body: dict[str, Any], perms: list[str]) -> list[dict[str, Any]]:
    raw = body.get("payments")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 10:
        raise OfflineError("پرداخت‌ها نامعتبر است", "validation_error", 400)
    out = []
    for p in raw:
        method = p.get("method") if isinstance(p, dict) else None
        if method not in ("cash", "card"):
            raise OfflineError(
                "در حالت آفلاین فقط پرداخت نقد و کارت (با کارت‌خوان جدا) ممکن است",
                "offline_unsupported",
            )
        if f"sales.payment.{method}" not in perms:
            raise OfflineError("مجوز این روش پرداخت را ندارید", "permission_denied", 403)
        if p.get("terminal_transaction_id"):
            raise OfflineError(
                "کارت‌خوان متصل در حالت آفلاین در دسترس نیست؛ شماره پیگیری را وارد کنید",
                "offline_unsupported",
            )
        amount = dec(p.get("amount"), "مبلغ پرداخت")
        if amount <= 0:
            raise OfflineError("مبلغ پرداخت نامعتبر است", "validation_error", 400)
        ref = p.get("card_reference")
        if method == "card" and (not ref or not str(ref).isdigit() or not 4 <= len(str(ref)) <= 32):
            raise OfflineError(
                "برای پرداخت کارتی شماره پیگیری رسید کارت‌خوان را وارد کنید",
                "card_reference_required",
            )
        out.append(
            {
                "method": method,
                "amount": m(amount),
                "card_reference": str(ref) if method == "card" else None,
            }
        )
    return out


def create_sale(store: Store, snap: Snapshot, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Record one sale in the local queue and return it as the server would (``Invoice``).

    Idempotent on the cart id, like the server's checkout."""
    sale_id = uid(body.get("id"), "شناسه فاکتور")
    done = store.op(sale_id)
    if done is not None:
        return done.view
    if snap.shift is None or snap.shift["user_id"] != user_id:
        raise OfflineError("شیفت باز این صندوق به نام شما نیست", "no_open_shift")
    if uid(body.get("cash_register_id"), "صندوق") != snap.register["id"]:
        raise OfflineError(
            "در حالت آفلاین فقط روی صندوق همین رایانه می‌توان فروخت", "not_found", 404
        )
    if body.get("customer_id") or body.get("approval_id"):
        raise OfflineError(
            "فروش نسیه و تأیید سرپرست در حالت آفلاین ممکن نیست", "offline_unsupported"
        )
    perms = permissions(snap)
    now = datetime.now(UTC)
    today = business_date(now)
    cart = price(snap, body, today)
    if (
        cart.manual_discount_total
        and "sales.invoice.discount_over_limit" not in perms
        and ("sales.invoice.discount" not in perms or cart.needs_discount_approval)
    ):
        raise OfflineError(
            "این تخفیف تأیید سرپرست می‌خواهد که در حالت آفلاین ممکن نیست", "offline_unsupported"
        )
    if cart.short and snap.settings["negative_stock_policy"] == "deny":
        raise OfflineError(cart.warnings[0] if cart.warnings else "موجودی کافی نیست", "no_stock")
    payments = _payments(body, perms)
    paid = sum((Decimal(p["amount"]) for p in payments), ZERO)
    if paid != cart.grand_total:
        raise OfflineError(
            f"جمع پرداخت‌ها ({plain(paid)}) با مبلغ فاکتور ({plain(cart.grand_total)}) برابر نیست",
            "payment_mismatch",
        )
    cash = sum((Decimal(p["amount"]) for p in payments if p["method"] == "cash"), ZERO)
    tendered = (
        dec(body["cash_tendered"], "وجه دریافتی") if body.get("cash_tendered") is not None else None
    )
    if tendered is not None and tendered < cash:
        raise OfflineError("وجه دریافتی از مبلغ نقدی کمتر است", "tendered_too_low")
    note = body.get("note")
    note = str(note)[:300] if note else None

    lines = [line_view(ln) for ln in cart.lines]
    stock: dict[str, Decimal] = {}
    for ln in cart.lines:
        if ln.item.item_type == "goods":
            stock[str(ln.item.id)] = stock.get(str(ln.item.id), ZERO) + ln.base_qty
    sold_at = now.isoformat()
    with store.tx() as db:
        again = db.execute("SELECT 1 FROM ops WHERE id = ?", (sale_id,)).fetchone()
        if again is not None:  # a concurrent retry got here first
            pass
        else:
            seq = store.next_seq(db)
            number = f"{snap.prefix}-{seq}"
            op = {
                "id": sale_id,
                "type": "sale",
                "local_time": sold_at,
                "sale": {
                    "id": sale_id,
                    "device_number": number,
                    "sold_at": sold_at,
                    "cash_register_id": snap.register["id"],
                    "shift_id": snap.shift["id"],
                    "user_id": user_id,
                    "snapshot_version": snap.version,
                    "prices_include_vat": bool(snap.settings["prices_include_vat"]),
                    "lines": [
                        {
                            k: ln[k]
                            for k in (
                                "item_id",
                                "unit_id",
                                "qty",
                                "unit_price",
                                "price_source",
                                "gross",
                                "promotion_id",
                                "promotion_discount",
                                "manual_discount",
                                "vat_exempt",
                                "vat_rate",
                                "tax",
                                "line_total",
                                "scanned_barcode",
                            )
                        }
                        for ln in lines
                    ],
                    "subtotal": m(cart.subtotal),
                    "discount_total": m(cart.discount_total),
                    "tax_total": m(cart.tax_total),
                    "grand_total": m(cart.grand_total),
                    "payments": payments,
                    "cash_tendered": m(tendered) if tendered is not None else None,
                    "note": note,
                },
            }
            view = {
                "id": sale_id,
                "kind": "sale",
                "status": "final",
                "number": None,
                "device_number": number,
                "offline": True,
                "document_date": today.isoformat(),
                "branch_id": snap.register["branch_id"],
                "cash_register_id": snap.register["id"],
                "register_name": snap.register["name"],
                "shift_id": snap.shift["id"],
                "cashier_name": snap.shift["user_name"],
                "customer_id": None,
                "customer_name": None,
                "original_invoice_id": None,
                "original_number": None,
                "subtotal": m(cart.subtotal),
                "discount_total": m(cart.discount_total),
                "tax_total": m(cart.tax_total),
                "grand_total": m(cart.grand_total),
                "cash_tendered": m(tendered) if tendered is not None else None,
                "change_due": m(tendered - cash) if tendered is not None else None,
                "note": note,
                "voucher_id": None,
                "finalized_at": sold_at,
                "created_at": sold_at,
                "lines": [
                    {
                        **ln,
                        "id": f"{sale_id}:{ln['line_no']}",
                        "cost_total": None,
                        "original_line_id": None,
                        "returned_qty": "0.000",
                    }
                    for ln in lines
                ],
                "payments": [{**p, "terminal_transaction_id": None} for p in payments],
                "warnings": cart.warnings,
            }
            store.add_op(
                db,
                op_id=sale_id,
                seq=seq,
                device_number=number,
                op=op,
                view=view,
                stock={k: q3(v) for k, v in stock.items()},
            )
    saved = store.op(sale_id)
    assert saved is not None
    return saved.view


def record_removal(store: Store, snap: Snapshot, user_id: str, body: dict[str, Any]) -> str:
    """A scanned line taken off the cart: queued for the server's audit log."""
    if snap.shift is None or snap.shift["user_id"] != user_id:
        raise OfflineError("شیفت باز این صندوق به نام شما نیست", "no_open_shift")
    if body.get("approval_id"):
        raise OfflineError("تأیید سرپرست در حالت آفلاین ممکن نیست", "offline_unsupported")
    item_id = uid(body.get("item_id"), "کالا")
    qty = dec(body.get("qty"), "مقدار", QTY)
    total = dec(body.get("line_total", "0"), "مبلغ")
    now = datetime.now(UTC).isoformat()
    op_id = str(uuid.uuid4())
    with store.tx() as db:
        seq = store.next_seq(db)
        store.add_op(
            db,
            op_id=op_id,
            seq=seq,
            device_number=f"{snap.prefix}-R{seq}",
            op={
                "id": op_id,
                "type": "line_removal",
                "local_time": now,
                "removal": {
                    "cash_register_id": snap.register["id"],
                    "shift_id": snap.shift["id"],
                    "user_id": user_id,
                    "item_id": item_id,
                    "qty": q3(qty),
                    "line_total": m(total),
                    "removed_at": now,
                },
            },
            view={"kind": "line_removal", "item_id": item_id, "qty": q3(qty)},
            stock={},
        )
    return op_id


# --- receipt ---------------------------------------------------------------------------


def _ns(view: dict[str, Any]) -> SimpleNamespace:
    """The view as the attribute object ``nextcam_core.receipt.build`` reads."""

    def money_or_none(v: str | None) -> Decimal | None:
        return Decimal(v) if v is not None else None

    return SimpleNamespace(
        kind=view["kind"],
        number=view["number"],
        finalized_at=datetime.fromisoformat(view["finalized_at"]),
        created_at=datetime.fromisoformat(view["created_at"]),
        register_name=view["register_name"],
        cashier_name=view["cashier_name"],
        customer_name=view["customer_name"],
        original_number=view["original_number"],
        subtotal=Decimal(view["subtotal"]),
        discount_total=Decimal(view["discount_total"]),
        tax_total=Decimal(view["tax_total"]),
        grand_total=Decimal(view["grand_total"]),
        cash_tendered=money_or_none(view["cash_tendered"]),
        change_due=money_or_none(view["change_due"]),
        lines=[
            SimpleNamespace(
                item_name=ln["item_name"],
                unit_name=ln["unit_name"],
                qty=Decimal(ln["qty"]),
                unit_price=Decimal(ln["unit_price"]),
                promotion_discount=Decimal(ln["promotion_discount"]),
                manual_discount=Decimal(ln["manual_discount"]),
                line_total=Decimal(ln["line_total"]),
                vat_exempt=ln["vat_exempt"],
            )
            for ln in view["lines"]
        ],
        payments=[
            SimpleNamespace(
                method=p["method"], amount=Decimal(p["amount"]), card_reference=p["card_reference"]
            )
            for p in view["payments"]
        ],
    )


def receipt(
    snap: Snapshot, view: dict[str, Any], *, reprint: bool, open_drawer: bool, cut: bool
) -> dict[str, Any]:
    st = snap.settings
    return build_receipt(
        _ns(view),
        organization=st["organization_name"],
        header=st["receipt_header"],
        footer=st["receipt_footer"],
        phone=st.get("phone"),
        address=st.get("address"),
        currency=st["display_currency"],
        timezone=st.get("timezone") or "Asia/Tehran",
        reprint=reprint,
        open_drawer=open_drawer,
        cut=cut,
        device_number=view["device_number"],
    )
