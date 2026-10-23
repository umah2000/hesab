"""Excel import of counterparties with opening balances (MASTER_PROMPT §12).

Balances are posted as one *draft* voucher from the ``parties.opening`` posting rule,
for the accountant to review and finalise. Existing codes are updated (contact and
identity only); an opening balance for an existing party is refused, so importing the
same file twice cannot double a balance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import excel
from app.core.errors import DomainError
from app.core.excel import ImportPreview, ImportResult, RowError
from app.modules.accounting.models import DetailAccount
from app.modules.accounting.services.posting import Entry, post_event
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.parties.models import Party
from app.modules.parties.schemas import PartyCreateIn, PartyUpdateIn
from app.modules.parties.services import core

ZERO = Decimal(0)
COLUMNS = [
    "کد *",
    "نام *",
    "نوع (حقیقی/حقوقی)",
    "مشتری",
    "تأمین‌کننده",
    "کد ملی / شناسه ملی",
    "کد اقتصادی",
    "موبایل",
    "تلفن",
    "کد پستی",
    "نشانی",
    "سقف اعتبار",
    "مانده بدهکار (طلب ما)",
    "مانده بستانکار (بدهی ما)",
]


# Typed in the credit-limit column instead of an amount: credit sales with no limit.
UNLIMITED = ("نامحدود", "unlimited")


def template(currency: str) -> bytes:
    unit = "تومان" if currency == "IRT" else "ریال"
    cols = [f"{c} ({unit})" if c.startswith(("سقف", "مانده")) else c for c in COLUMNS]
    return excel.template(
        cols,
        "طرف‌حساب‌ها",
        [
            "C100",
            "رستوران آفتاب",
            "حقوقی",
            "بله",
            "خیر",
            "",
            "",
            "09120000000",
            "",
            "",
            "",
            "5000000",
            "1200000",
            "",
        ],
        "ستون‌های ستاره‌دار الزامی است. ردیف نمونه را پیش از ورود حذف کنید.\n"
        "مشتری / تأمین‌کننده: بله یا خیر؛ دست‌کم یکی بله.\n"
        "کد ملی (حقیقی) با رقم کنترل بررسی می‌شود.\n"
        f"مبالغ به {unit}. مانده بدهکار = طرف‌حساب به ما بدهکار است؛ مانده بستانکار = ما بدهکاریم.\n"
        "مانده‌ها به‌صورت یک «سند افتتاحیه» پیش‌نویس ثبت می‌شوند که حسابدار پس از بررسی قطعی می‌کند.\n"
        "اگر کد از قبل وجود داشته باشد، اطلاعات تماس و شناسه‌ها به‌روز می‌شود "
        "و مانده افتتاحیه پذیرفته نمی‌شود.",
        text_columns=("A", "F", "G", "H", "I", "J"),
        yes_no_columns=("D", "E"),
    )


@dataclass
class _Row:
    row: int
    code: str
    data: dict[str, Any]
    debit: Decimal
    credit: Decimal
    existing: bool


def _parse(s: Session, file_bytes: bytes, currency: str) -> tuple[list[_Row], list[RowError], int]:
    raw = excel.read_rows(file_bytes, len(COLUMNS))
    existing = {
        d.code: d.id for d in s.scalars(select(DetailAccount).where(DetailAccount.kind == "person"))
    }
    rows: list[_Row] = []
    errors: list[RowError] = []
    seen: set[str] = set()
    for idx, v in raw:

        def err(col: int, msg: str, idx: int = idx) -> None:
            errors.append(RowError(row=idx, column=COLUMNS[col], message=msg))

        code = excel.text(v[0]).upper()
        if code in seen:
            err(0, "کد تکراری در فایل")
            continue
        seen.add(code)
        try:
            kind = excel.text(v[2])
            party_type = "company" if kind in ("حقوقی", "شرکت", "company") else "person"
            is_customer = excel.yes_no(v[3]) if excel.text(v[3]) else True
            is_supplier = excel.yes_no(v[4]) if excel.text(v[4]) else False
        except ValueError as e:
            err(3, str(e))
            continue
        money: list[Decimal] = []
        bad = False
        unlimited = excel.text(v[11]) in UNLIMITED
        for col in (12, 13) if unlimited else (11, 12, 13):
            try:
                money.append(excel.to_rials(v[col], currency) if excel.text(v[col]) else ZERO)
            except ValueError as e:
                err(col, str(e))
                bad = True
        if bad:
            continue
        limit, debit, credit = [ZERO, *money] if unlimited else money
        if debit and credit:
            err(12, "فقط یکی از مانده بدهکار یا بستانکار")
            continue
        fields: dict[str, Any] = {
            "name": excel.text(v[1]),
            "party_type": party_type,
            "is_customer": is_customer,
            "is_supplier": is_supplier,
            "national_id": excel.text(v[5]) or None,
            "economic_code": excel.text(v[6]) or None,
            "mobile": excel.text(v[7]) or None,
            "phone": excel.text(v[8]) or None,
            "postal_code": excel.text(v[9]) or None,
            "address": excel.text(v[10]) or None,
            "credit_limit": limit if limit else None,
            "credit_unlimited": unlimited,
        }
        try:
            if code in existing:
                PartyUpdateIn.model_validate(fields)
            else:
                PartyCreateIn.model_validate({"code": code, **fields})
        except ValidationError as e:
            first = e.errors()[0]
            loc = str(first["loc"][0]) if first["loc"] else ""
            col = {
                "code": 0,
                "name": 1,
                "national_id": 5,
                "economic_code": 6,
                "mobile": 7,
                "phone": 8,
                "postal_code": 9,
            }.get(loc, 1)
            err(col, str(first["msg"]).replace("Value error, ", ""))
            continue
        if code in existing and (debit or credit):
            err(12, "طرف‌حساب از قبل وجود دارد؛ مانده افتتاحیه فقط برای طرف‌حساب جدید")
            continue
        rows.append(_Row(idx, code, fields, debit, credit, code in existing))
    return rows, errors, len(raw)


def preview(s: Session, file_bytes: bytes, currency: str) -> ImportPreview:
    rows, errors, total = _parse(s, file_bytes, currency)
    return ImportPreview(
        total_rows=total,
        valid_rows=len(rows),
        to_create=sum(1 for r in rows if not r.existing),
        to_update=sum(1 for r in rows if r.existing),
        errors=errors[:500],
        sample=[{"code": r.code, "name": r.data["name"]} for r in rows[:5]],
    )


def commit(
    s: Session, actor: Actor, file_bytes: bytes, currency: str, opening_date: date
) -> ImportResult:
    rows, errors, _ = _parse(s, file_bytes, currency)
    if errors:
        raise DomainError("فایل خطا دارد؛ ابتدا خطاها را اصلاح کنید", code="import_has_errors")
    created = updated = 0
    entries: list[Entry] = []
    for r in rows:
        if r.existing:
            d = s.scalar(select(DetailAccount).where(DetailAccount.code == r.code))
            assert d is not None
            p = s.get(Party, d.id) or core.ensure_party(s, d.id)
            core.apply_fields(p, d, PartyUpdateIn.model_validate(r.data))
            updated += 1
            continue
        out = core.create(s, actor, PartyCreateIn.model_validate({"code": r.code, **r.data}))
        created += 1
        if r.debit:
            entries += [
                Entry("receivable", debit=r.debit, detail_account_id=out.id),
                Entry("offset", credit=r.debit),
            ]
        if r.credit:
            entries += [
                Entry("payable", credit=r.credit, detail_account_id=out.id),
                Entry("offset", debit=r.credit),
            ]
    voucher_id = None
    if entries:
        v = post_event(
            s,
            event_type="parties.opening",
            document_date=opening_date,
            branch_id=None,
            entries=entries,
            actor_id=actor.user_id,
            description="مانده افتتاحیه طرف‌حساب‌ها (ورود از Excel)",
            draft=True,
        )
        voucher_id = v.id
    audit.record(
        s,
        "parties.imported",
        user_id=actor.user_id,
        data={"created": created, "updated": updated, "voucher": str(voucher_id)},
    )
    return ImportResult(created=created, updated=updated, document_id=voucher_id)
