"""Excel import: items (create or update) and opening stock (as a draft document).

Two steps with the same file: preview (row-by-row validation, nothing saved) and
commit (all-or-nothing; refused while any row has an error).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import jdatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import excel
from app.core.errors import DomainError
from app.core.excel import ImportPreview, ImportResult, RowError
from app.core.excel import decimal as _decimal
from app.core.excel import read_rows as _read
from app.core.excel import text as _text
from app.core.excel import to_rials as _to_rials
from app.core.excel import yes_no as _bool
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.inventory.models import (
    Item,
    ItemBarcode,
    ItemGroup,
    ItemPrice,
    ScaleBarcodeRule,
    Unit,
)
from app.modules.inventory.schemas import StockDocIn, StockLineIn
from app.modules.inventory.services.catalog import default_price_list, normalize_scan
from app.modules.inventory.services.stock import create_doc

ITEM_COLUMNS = [
    "کد کالا *",
    "نام کالا *",
    "گروه",
    "واحد *",
    "بارکدها (با ویرگول)",
    "قیمت فروش",
    "وزنی",
    "کد ترازو",
    "معاف از مالیات",
    "نرخ مالیات (%)",
    "حداقل موجودی",
]
OPENING_COLUMNS = ["کد کالا یا بارکد *", "مقدار *", "بهای واحد *", "تاریخ انقضا (شمسی)"]


def _template(columns: list[str], title: str, example: list[Any], note: str) -> bytes:
    if title == "کالاها":
        return excel.template(
            columns, title, example, note, text_columns=("A", "E", "H"), yes_no_columns=("G", "I")
        )
    return excel.template(columns, title, example, note)


def items_template(currency: str) -> bytes:
    unit = "تومان" if currency == "IRT" else "ریال"
    return _template(
        [c if c != "قیمت فروش" else f"قیمت فروش ({unit})" for c in ITEM_COLUMNS],
        "کالاها",
        [
            "1001",
            "شیر پرچرب ۱ لیتری",
            "لبنیات",
            "عدد",
            "6260100212345",
            "42000",
            "خیر",
            "",
            "بله",
            "",
            "24",
        ],
        "ستون‌های ستاره‌دار الزامی است. ردیف نمونه را پیش از ورود حذف کنید.\n"
        "واحد: نام یا کد واحد (عدد، کیلوگرم، بسته، کارتن …).\n"
        "گروه: نام گروه؛ اگر وجود نداشته باشد ساخته می‌شود.\n"
        "اگر کد کالا از قبل وجود داشته باشد، نام، گروه، قیمت و بارکدهای جدید آن "
        "به‌روز می‌شود (بارکد قبلی حذف نمی‌شود).\n"
        f"قیمت به {unit} و به واحد اصلی کالا است. "
        "کد ترازو فقط برای کالاهایی که با ترازوی برچسب‌زن فروخته می‌شوند.\n"
        "معاف از مالیات و نرخ مالیات را با حسابدار فروشگاه بررسی کنید.",
    )


def opening_template(currency: str) -> bytes:
    unit = "تومان" if currency == "IRT" else "ریال"
    return _template(
        [c if c != "بهای واحد *" else f"بهای واحد * ({unit})" for c in OPENING_COLUMNS],
        "موجودی",
        ["1001", "120", "35000", ""],
        "مقدار به واحد اصلی کالا (برای کالای وزنی به کیلوگرم).\n"
        f"بهای واحد = بهای تمام‌شده خرید هر واحد به {unit}، نه قیمت فروش.\n"
        "نتیجه ورود یک «سند موجودی اول دوره» پیش‌نویس است؛ پس از بررسی آن را قطعی کنید.",
    )


@dataclass
class _ItemRow:
    row: int
    code: str
    name: str
    group: str
    unit_id: uuid.UUID
    barcodes: list[str]
    price: Decimal | None
    weighted: bool
    scale_code: str | None
    vat_exempt: bool
    vat_rate: Decimal | None
    min_qty: Decimal | None
    exists: bool = False


@dataclass
class _Parsed:
    rows: list[_ItemRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def _parse_items(s: Session, file_bytes: bytes, currency: str) -> _Parsed:
    raw = _read(file_bytes, len(ITEM_COLUMNS))
    units: dict[str, uuid.UUID] = {}
    for u in s.scalars(select(Unit)):
        units[u.code.lower()] = u.id
        units[u.name] = u.id
    existing_codes = {c.lower() for c in s.scalars(select(Item.code))}
    barcode_owner = {
        b: c.lower()
        for b, c in s.execute(
            select(ItemBarcode.barcode, Item.code).join(Item, Item.id == ItemBarcode.item_id)
        )
    }
    scale_owner = {
        sc: c.lower()
        for sc, c in s.execute(
            select(Item.scale_code, Item.code).where(Item.scale_code.is_not(None))
        )
    }
    prefixes = [r.prefix for r in s.scalars(select(ScaleBarcodeRule)) if r.is_active]
    out = _Parsed()
    seen_codes: set[str] = set()
    seen_barcodes: dict[str, int] = {}
    seen_scale: dict[str, int] = {}
    for n, v in raw:
        errs: list[RowError] = []

        def err(c: int, msg: str, n: int = n, errs: list[RowError] = errs) -> None:
            errs.append(RowError(row=n, column=ITEM_COLUMNS[c].replace(" *", ""), message=msg))

        code, name = _text(v[0]), _text(v[1])
        if not code:
            err(0, "الزامی است")
        elif len(code) > 32 or not all(ch.isalnum() or ch in "-._" for ch in code):
            err(0, "فقط حرف لاتین، عدد و - . _ (حداکثر ۳۲)")
        elif code.lower() in seen_codes:
            err(0, "در فایل تکرار شده است")
        seen_codes.add(code.lower())
        if len(name) < 2:
            err(1, "الزامی است")
        unit_id = units.get(_text(v[3]).lower()) or units.get(_text(v[3]))
        if unit_id is None:
            err(3, f"واحد «{_text(v[3])}» تعریف نشده است")
        barcodes = [
            normalize_scan(b) for b in _text(v[4]).replace("،", ",").split(",") if b.strip()
        ]
        for b in barcodes:
            if not (3 <= len(b) <= 48):
                err(4, f"بارکد {b} نامعتبر است")
            elif b in barcode_owner and barcode_owner[b] != code.lower():
                err(4, f"بارکد {b} متعلق به کالای {barcode_owner[b]} است")
            elif b in seen_barcodes and seen_barcodes[b] != n:
                err(4, f"بارکد {b} در ردیف {seen_barcodes[b]} هم آمده است")
            elif len(b) == 13 and any(b.startswith(p) for p in prefixes):
                err(4, f"بارکد {b} با پیشوند بارکد ترازو شروع می‌شود")
            seen_barcodes[b] = n
        price = None
        if _text(v[5]):
            try:
                price = _to_rials(v[5], currency)
            except ValueError as e:
                err(5, str(e))
        flags = {}
        for i, key in ((6, "weighted"), (8, "vat_exempt")):
            try:
                flags[key] = _bool(v[i])
            except ValueError as e:
                err(i, str(e))
                flags[key] = False
        scale = _text(v[7]) or None
        if scale:
            if not scale.isdigit() or len(scale) > 8:
                err(7, "فقط عدد (حداکثر ۸ رقم)")
            elif scale_owner.get(scale, code.lower()) != code.lower():
                err(7, f"متعلق به کالای {scale_owner[scale]} است")
            elif scale in seen_scale:
                err(7, f"در ردیف {seen_scale[scale]} هم آمده است")
            seen_scale[scale] = n
        vat_rate = min_qty = None
        if _text(v[9]):
            try:
                vat_rate = _decimal(v[9], "0.01")
                if not 0 <= vat_rate <= 100:
                    raise ValueError("بین ۰ تا ۱۰۰")
            except ValueError as e:
                err(9, str(e))
        if _text(v[10]):
            try:
                min_qty = _decimal(v[10], "0.001")
            except ValueError as e:
                err(10, str(e))
        if errs:
            out.errors.extend(errs)
            continue
        out.rows.append(
            _ItemRow(
                row=n,
                code=code,
                name=name,
                group=_text(v[2]),
                unit_id=unit_id,  # type: ignore[arg-type]
                barcodes=barcodes,
                price=price,
                weighted=flags["weighted"],
                scale_code=scale,
                vat_exempt=flags["vat_exempt"],
                vat_rate=vat_rate,
                min_qty=min_qty,
                exists=code.lower() in existing_codes,
            )
        )
    return out


def preview_items(s: Session, file_bytes: bytes, currency: str) -> ImportPreview:
    p = _parse_items(s, file_bytes, currency)
    return ImportPreview(
        total_rows=len(p.rows) + len({e.row for e in p.errors}),
        valid_rows=len(p.rows),
        to_create=sum(1 for r in p.rows if not r.exists),
        to_update=sum(1 for r in p.rows if r.exists),
        errors=p.errors[:500],
        sample=[
            {
                "row": r.row,
                "code": r.code,
                "name": r.name,
                "group": r.group,
                "barcodes": ", ".join(r.barcodes),
                "price": str(r.price) if r.price is not None else None,
                "action": "update" if r.exists else "create",
            }
            for r in p.rows[:20]
        ],
    )


def commit_items(s: Session, actor: Actor, file_bytes: bytes, currency: str) -> ImportResult:
    p = _parse_items(s, file_bytes, currency)
    if p.errors:
        raise DomainError(
            f"{len({e.row for e in p.errors})} ردیف خطا دارد؛ ابتدا فایل را اصلاح کنید",
            code="import_has_errors",
        )
    if not p.rows:
        raise DomainError("فایل ردیفی ندارد", code="empty_import")
    groups = {g.name: g for g in s.scalars(select(ItemGroup))}
    group_codes = {g.code for g in groups.values()}
    next_group = len(groups) + 1
    items = {i.code.lower(): i for i in s.scalars(select(Item))}
    pl = default_price_list(s).id
    prices = {
        (pr.item_id, pr.unit_id): pr
        for pr in s.scalars(select(ItemPrice).where(ItemPrice.price_list_id == pl))
    }
    created = updated = 0
    new_groups: list[ItemGroup] = []
    new_items: list[Item] = []
    new_children: list[ItemBarcode | ItemPrice] = []
    # No queries inside the loop: ids are assigned up front so everything is
    # written by one batched flush at the end (autoflush would otherwise flush per row).
    with s.no_autoflush:
        for r in p.rows:
            group = None
            if r.group:
                group = groups.get(r.group)
                if group is None:
                    while f"G{next_group:03d}" in group_codes:
                        next_group += 1
                    code = f"G{next_group:03d}"
                    group_codes.add(code)
                    group = ItemGroup(
                        id=uuid.uuid4(), code=code, name=r.group[:100], created_by=actor.user_id
                    )
                    new_groups.append(group)
                    groups[r.group] = group
            it = items.get(r.code.lower())
            if it is None:
                it = Item(
                    id=uuid.uuid4(),
                    code=r.code,
                    name=r.name[:200],
                    group_id=group.id if group else None,
                    base_unit_id=r.unit_id,
                    item_type="goods",
                    is_weighted=r.weighted,
                    scale_code=r.scale_code,
                    track_expiry=False,
                    vat_exempt=r.vat_exempt,
                    vat_rate=r.vat_rate,
                    min_qty=r.min_qty,
                    is_active=True,
                    created_by=actor.user_id,
                    updated_by=actor.user_id,
                )
                new_items.append(it)
                items[r.code.lower()] = it
                have: set[str] = set()
                created += 1
            else:
                it.name, it.is_weighted, it.vat_exempt = r.name[:200], r.weighted, r.vat_exempt
                it.group_id = group.id if group else it.group_id
                it.scale_code = r.scale_code or it.scale_code
                it.vat_rate = r.vat_rate if r.vat_rate is not None else it.vat_rate
                it.min_qty = r.min_qty if r.min_qty is not None else it.min_qty
                it.updated_by = actor.user_id
                have = {b.barcode for b in it.barcodes}
                updated += 1
            for b in r.barcodes:
                if b not in have:
                    new_children.append(ItemBarcode(id=uuid.uuid4(), barcode=b, item_id=it.id))
            if r.price is not None:
                row = prices.get((it.id, r.unit_id))
                if row is None:
                    new_children.append(
                        ItemPrice(
                            id=uuid.uuid4(),
                            price_list_id=pl,
                            item_id=it.id,
                            unit_id=r.unit_id,
                            price=r.price,
                            created_by=actor.user_id,
                        )
                    )
                else:
                    row.price = r.price
    # Parents before children; each stage is one batched INSERT per table.
    for batch in (new_groups, new_items, new_children):
        s.add_all(batch)
        s.flush()
    audit.record(
        s,
        "inventory.items_imported",
        user_id=actor.user_id,
        data={"created": created, "updated": updated, "rows": len(p.rows)},
    )
    return ImportResult(created=created, updated=updated)


@dataclass
class _OpeningRow:
    row: int
    item_id: uuid.UUID
    qty: Decimal
    cost: Decimal
    expiry: date | None


def _parse_opening(
    s: Session, file_bytes: bytes, currency: str
) -> tuple[list[_OpeningRow], list[RowError]]:
    raw = _read(file_bytes, len(OPENING_COLUMNS))
    by_code = {
        c.lower(): (i, t) for c, i, t in s.execute(select(Item.code, Item.id, Item.item_type))
    }
    by_barcode = dict(s.execute(select(ItemBarcode.barcode, ItemBarcode.item_id)).tuples().all())
    rows: list[_OpeningRow] = []
    errors: list[RowError] = []
    seen: dict[uuid.UUID, int] = {}
    for n, v in raw:

        def err(c: int, msg: str, n: int = n) -> None:
            errors.append(RowError(row=n, column=OPENING_COLUMNS[c].replace(" *", ""), message=msg))

        key = _text(v[0])
        found = by_code.get(key.lower())
        item_id = found[0] if found else by_barcode.get(normalize_scan(key))
        if item_id is None:
            err(0, f"کالای «{key}» یافت نشد")
            continue
        if found and found[1] != "goods":
            err(0, "خدمت موجودی ندارد")
            continue
        if item_id in seen:
            err(0, f"در ردیف {seen[item_id]} هم آمده است")
            continue
        seen[item_id] = n
        try:
            qty = _decimal(v[1], "0.001")
            if qty <= 0:
                raise ValueError("باید مثبت باشد")
        except ValueError as e:
            err(1, str(e))
            continue
        try:
            cost = _to_rials(v[2], currency)
        except ValueError as e:
            err(2, str(e))
            continue
        expiry = None
        if _text(v[3]):
            try:
                y, m, d = (int(x) for x in _text(v[3]).replace("-", "/").split("/"))
                expiry = jdatetime.date(y, m, d).togregorian()
            except (ValueError, TypeError):
                err(3, "تاریخ شمسی نامعتبر (مثلاً 1405/09/30)")
                continue
        rows.append(_OpeningRow(n, item_id, qty, cost, expiry))
    return rows, errors


def preview_opening(s: Session, file_bytes: bytes, currency: str) -> ImportPreview:
    rows, errors = _parse_opening(s, file_bytes, currency)
    return ImportPreview(
        total_rows=len(rows) + len({e.row for e in errors}),
        valid_rows=len(rows),
        to_create=len(rows),
        to_update=0,
        errors=errors[:500],
        sample=[{"row": r.row, "qty": str(r.qty), "cost": str(r.cost)} for r in rows[:20]],
    )


def commit_opening(
    s: Session,
    actor: Actor,
    file_bytes: bytes,
    currency: str,
    warehouse_id: uuid.UUID,
    document_date: date,
) -> ImportResult:
    rows, errors = _parse_opening(s, file_bytes, currency)
    if errors:
        raise DomainError(
            f"{len({e.row for e in errors})} ردیف خطا دارد؛ ابتدا فایل را اصلاح کنید",
            code="import_has_errors",
        )
    if not rows:
        raise DomainError("فایل ردیفی ندارد", code="empty_import")
    doc = create_doc(
        s,
        actor,
        StockDocIn(
            doc_type="opening",
            warehouse_id=warehouse_id,
            document_date=document_date,
            description="ورود موجودی اول دوره از Excel",
            lines=[
                StockLineIn(item_id=r.item_id, qty=r.qty, unit_cost=r.cost, expiry_date=r.expiry)
                for r in rows
            ],
        ),
    )
    audit.record(
        s,
        "inventory.opening_imported",
        user_id=actor.user_id,
        entity_type="stock_document",
        entity_id=doc.id,
        data={"rows": len(rows)},
    )
    return ImportResult(created=len(rows), updated=0, document_id=doc.id)
