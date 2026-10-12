"""Bank statements: Excel import, matching to the books, reconciliation (مغایرت‌گیری).

A statement line matches exactly one voucher line of the same bank account with the
same signed amount. Auto-match only pairs lines with a single candidate within a few
days; everything else is matched by hand. Matching never changes a voucher.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import jdatetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import excel
from app.core.db import utcnow
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.excel import RowError
from app.core.http import Page
from app.modules.accounting.models import Voucher, VoucherLine
from app.modules.audit import service as audit
from app.modules.iam.guard import Actor
from app.modules.treasury.models import BankStatementLine, MoneyAccount
from app.modules.treasury.schemas import (
    AutoMatchOut,
    BookLineOut,
    ReconciliationOut,
    StatementImportOut,
    StatementLineOut,
    StatementQuery,
)
from app.modules.treasury.services import accounts

ZERO = Decimal(0)
MATCH_DAYS = 5
COLUMNS = ["تاریخ *", "شرح", "شماره پیگیری / سند", "واریز (ریال)", "برداشت (ریال)", "مانده (ریال)"]


def template() -> bytes:
    return excel.template(
        COLUMNS,
        "صورتحساب بانک",
        ["1405/02/11", "واریز پایا", "123456", "5000000", "", "125000000"],
        "هر ردیف یک گردش بانک است؛ فقط یکی از «واریز» یا «برداشت» پر شود.\n"
        "تاریخ شمسی (۱۴۰۵/۰۲/۱۱) یا میلادی پذیرفته می‌شود.\n"
        "مبالغ به ریال، همان‌طور که بانک چاپ کرده.\n"
        "ستون «مانده» اختیاری است و برای کنترل مغایرت به کار می‌رود.\n"
        "اگر صورتحساب هم‌پوشان دوباره وارد شود، ردیف‌های تکراری نادیده گرفته می‌شوند.",
        text_columns=("A", "C"),
    )


def parse_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = excel.text(v).replace("-", "/").replace(".", "/")
    parts = t.split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("تاریخ نامعتبر (مثال: ۱۴۰۵/۰۲/۱۱)")
    y, m, d = (int(p) for p in parts)
    try:
        if y < 1700:
            g: date = jdatetime.date(y, m, d).togregorian()
            return g
        return date(y, m, d)
    except ValueError as e:
        raise ValueError("تاریخ نامعتبر") from e


def _parse(
    s: Session, account_id: uuid.UUID, file_bytes: bytes
) -> tuple[list[dict[str, Any]], list[RowError], int, int]:
    raw = excel.read_rows(file_bytes, len(COLUMNS))
    known = set(
        s.scalars(
            select(BankStatementLine.fingerprint).where(
                BankStatementLine.money_account_id == account_id
            )
        )
    )
    rows: list[dict[str, Any]] = []
    errors: list[RowError] = []
    seen: dict[str, int] = {}
    dupes = 0
    for idx, v in raw:

        def err(col: int, msg: str, idx: int = idx) -> None:
            errors.append(RowError(row=idx, column=COLUMNS[col], message=msg))

        try:
            when = parse_date(v[0])
        except ValueError as e:
            err(0, str(e))
            continue
        amounts: list[Decimal] = []
        bad = False
        for col in (3, 4, 5):
            try:
                amounts.append(excel.decimal(v[col], "1") if excel.text(v[col]) else ZERO)
            except ValueError as e:
                err(col, str(e))
                bad = True
        if bad:
            continue
        dep, wd, bal = amounts
        if (dep and wd) or not (dep or wd) or dep < 0 or wd < 0:
            err(3, "دقیقاً یکی از واریز یا برداشت (مثبت) را وارد کنید")
            continue
        amount = dep if dep else -wd
        desc = excel.text(v[1])[:300] or None
        ref = excel.text(v[2])[:60] or None
        balance = bal if excel.text(v[5]) else None
        key = f"{when.isoformat()}|{amount:f}|{ref or ''}|{desc or ''}|{balance or ''}"
        # Two identical lines in one statement are two transactions, not a duplicate.
        n = seen.get(key, 0) + 1
        seen[key] = n
        fp = hashlib.sha256(f"{key}#{n}".encode()).hexdigest()
        if fp in known:
            dupes += 1
            continue
        rows.append(
            {
                "line_date": when,
                "amount": amount,
                "description": desc,
                "reference": ref,
                "balance": balance,
                "fingerprint": fp,
            }
        )
    return rows, errors, len(raw), dupes


def _bank(s: Session, actor: Actor, account_id: uuid.UUID) -> MoneyAccount:
    m, _ = accounts.require(s, actor, account_id, "bank")
    return m


def preview(s: Session, actor: Actor, account_id: uuid.UUID, data: bytes) -> StatementImportOut:
    _bank(s, actor, account_id)
    rows, errors, total, dupes = _parse(s, account_id, data)
    return StatementImportOut(
        total_rows=total,
        new_rows=len(rows),
        duplicate_rows=dupes,
        errors=errors[:500],
        sample=[
            {"line_date": r["line_date"].isoformat(), "amount": f"{r['amount']:f}"}
            for r in rows[:5]
        ],
    )


def commit(s: Session, actor: Actor, account_id: uuid.UUID, data: bytes) -> StatementImportOut:
    m = s.get(MoneyAccount, _bank(s, actor, account_id).id, with_for_update=True)
    assert m is not None
    rows, errors, total, dupes = _parse(s, account_id, data)
    if errors:
        raise DomainError("فایل خطا دارد؛ ابتدا خطاها را اصلاح کنید", code="import_has_errors")
    seq = (
        s.scalar(
            select(func.max(BankStatementLine.seq)).where(
                BankStatementLine.money_account_id == account_id
            )
        )
        or 0
    )
    for r in rows:
        seq += 1
        s.add(
            BankStatementLine(
                money_account_id=account_id,
                seq=seq,
                created_by=actor.user_id,
                updated_by=actor.user_id,
                **r,
            )
        )
    s.flush()
    audit.record(
        s,
        "treasury.statement_imported",
        user_id=actor.user_id,
        entity_type="money_account",
        entity_id=account_id,
        data={"new": len(rows), "duplicates": dupes},
    )
    return StatementImportOut(
        total_rows=total, new_rows=len(rows), duplicate_rows=dupes, errors=[], sample=[]
    )


# --- listing ----------------------------------------------------------------


def _line_out(s: Session, ln: BankStatementLine) -> StatementLineOut:
    vl = s.get(VoucherLine, ln.voucher_line_id) if ln.voucher_line_id else None
    v = s.get(Voucher, vl.voucher_id) if vl else None
    return StatementLineOut(
        id=ln.id,
        line_date=ln.line_date,
        amount=ln.amount,
        description=ln.description,
        reference=ln.reference,
        balance=ln.balance,
        voucher_line_id=ln.voucher_line_id,
        voucher_id=v.id if v else None,
        voucher_number=v.number if v else None,
        matched_at=ln.matched_at,
    )


def list_lines(
    s: Session, actor: Actor, account_id: uuid.UUID, q: StatementQuery
) -> Page[StatementLineOut]:
    _bank(s, actor, account_id)
    stmt = select(BankStatementLine).where(BankStatementLine.money_account_id == account_id)
    if q.matched is not None:
        stmt = stmt.where(
            BankStatementLine.voucher_line_id.is_not(None)
            if q.matched
            else BankStatementLine.voucher_line_id.is_(None)
        )
    if q.date_from:
        stmt = stmt.where(BankStatementLine.line_date >= q.date_from)
    if q.date_to:
        stmt = stmt.where(BankStatementLine.line_date <= q.date_to)
    total = s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        s.scalars(
            stmt.order_by(BankStatementLine.line_date, BankStatementLine.seq)
            .offset((q.page - 1) * q.page_size)
            .limit(q.page_size)
        )
    )
    return Page(
        items=[_line_out(s, r) for r in rows], total=total, page=q.page, page_size=q.page_size
    )


def _book(
    s: Session, account_id: uuid.UUID, *, unmatched: bool, until: date | None = None
) -> list[BookLineOut]:
    matched = select(BankStatementLine.voucher_line_id).where(
        BankStatementLine.voucher_line_id.is_not(None)
    )
    stmt = (
        select(VoucherLine, Voucher)
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(Voucher.status == "final", VoucherLine.detail_account_id == account_id)
    )
    if unmatched:
        stmt = stmt.where(VoucherLine.id.not_in(matched))
    if until:
        stmt = stmt.where(Voucher.document_date <= until)
    return [
        BookLineOut(
            voucher_line_id=vl.id,
            voucher_id=v.id,
            voucher_number=v.number,
            document_date=v.document_date,
            description=vl.description or v.description,
            amount=vl.debit - vl.credit,
        )
        for vl, v in s.execute(stmt.order_by(Voucher.document_date, Voucher.number)).all()
    ]


def candidates(s: Session, actor: Actor, line_id: uuid.UUID) -> list[BookLineOut]:
    ln = _line(s, actor, line_id)
    lo, hi = ln.line_date - timedelta(days=30), ln.line_date + timedelta(days=30)
    return [
        b
        for b in _book(s, ln.money_account_id, unmatched=True)
        if b.amount == ln.amount and lo <= b.document_date <= hi
    ]


def _line(s: Session, actor: Actor, line_id: uuid.UUID, lock: bool = False) -> BankStatementLine:
    ln = s.get(BankStatementLine, line_id, with_for_update=lock)
    if ln is None:
        raise NotFoundError("ردیف صورتحساب یافت نشد")
    _bank(s, actor, ln.money_account_id)
    return ln


# --- matching ---------------------------------------------------------------


def match(
    s: Session, actor: Actor, line_id: uuid.UUID, voucher_line_id: uuid.UUID
) -> StatementLineOut:
    ln = _line(s, actor, line_id, lock=True)
    if ln.voucher_line_id is not None:
        raise ConflictError("این ردیف قبلاً تطبیق داده شده است", code="already_matched")
    vl = s.get(VoucherLine, voucher_line_id)
    v = s.get(Voucher, vl.voucher_id) if vl else None
    if (
        vl is None
        or v is None
        or v.status != "final"
        or vl.detail_account_id != ln.money_account_id
    ):
        raise DomainError("ردیف سند متعلق به این حساب بانکی نیست", code="bad_voucher_line")
    if vl.debit - vl.credit != ln.amount:
        raise DomainError("مبلغ ردیف سند با ردیف صورتحساب برابر نیست", code="amount_mismatch")
    if s.scalar(select(BankStatementLine.id).where(BankStatementLine.voucher_line_id == vl.id)):
        raise ConflictError("این ردیف سند با ردیف دیگری تطبیق شده است", code="already_matched")
    ln.voucher_line_id, ln.matched_at, ln.matched_by = vl.id, utcnow(), actor.user_id
    ln.updated_by = actor.user_id
    s.flush()
    return _line_out(s, ln)


def unmatch(s: Session, actor: Actor, line_id: uuid.UUID) -> StatementLineOut:
    ln = _line(s, actor, line_id, lock=True)
    ln.voucher_line_id = ln.matched_at = ln.matched_by = None
    ln.updated_by = actor.user_id
    s.flush()
    return _line_out(s, ln)


def auto_match(s: Session, actor: Actor, account_id: uuid.UUID) -> AutoMatchOut:
    m = s.get(MoneyAccount, _bank(s, actor, account_id).id, with_for_update=True)
    assert m is not None
    lines = list(
        s.scalars(
            select(BankStatementLine)
            .where(
                BankStatementLine.money_account_id == account_id,
                BankStatementLine.voucher_line_id.is_(None),
            )
            .order_by(BankStatementLine.line_date, BankStatementLine.seq)
        )
    )
    book = _book(s, account_id, unmatched=True)
    used: set[uuid.UUID] = set()
    matched = ambiguous = 0
    now = utcnow()
    for ln in lines:
        window = timedelta(days=MATCH_DAYS)
        found = [
            b
            for b in book
            if b.voucher_line_id not in used
            and b.amount == ln.amount
            and abs(b.document_date - ln.line_date) <= window
        ]
        if len(found) == 1:
            used.add(found[0].voucher_line_id)
            ln.voucher_line_id, ln.matched_at, ln.matched_by = (
                found[0].voucher_line_id,
                now,
                actor.user_id,
            )
            matched += 1
        elif found:
            ambiguous += 1
    s.flush()
    audit.record(
        s,
        "treasury.statement_auto_matched",
        user_id=actor.user_id,
        entity_type="money_account",
        entity_id=account_id,
        data={"matched": matched, "ambiguous": ambiguous},
    )
    return AutoMatchOut(
        matched=matched, ambiguous=ambiguous, unmatched=len(lines) - matched - ambiguous
    )


def reconciliation(
    s: Session, actor: Actor, account_id: uuid.UUID, as_of: date
) -> ReconciliationOut:
    _bank(s, actor, account_id)
    book_balance = sum((b.amount for b in _book(s, account_id, unmatched=False, until=as_of)), ZERO)
    book_open = _book(s, account_id, unmatched=True, until=as_of)
    stmt_open = list(
        s.scalars(
            select(BankStatementLine)
            .where(
                BankStatementLine.money_account_id == account_id,
                BankStatementLine.voucher_line_id.is_(None),
                BankStatementLine.line_date <= as_of,
            )
            .order_by(BankStatementLine.line_date, BankStatementLine.seq)
        )
    )
    last = s.scalar(
        select(BankStatementLine)
        .where(
            BankStatementLine.money_account_id == account_id,
            BankStatementLine.line_date <= as_of,
            BankStatementLine.balance.is_not(None),
        )
        .order_by(BankStatementLine.line_date.desc(), BankStatementLine.seq.desc())
        .limit(1)
    )
    return ReconciliationOut(
        account_id=account_id,
        as_of=as_of,
        book_balance=book_balance,
        statement_balance=last.balance if last else None,
        statement_unmatched=[_line_out(s, ln) for ln in stmt_open],
        book_unmatched=book_open,
        adjusted_book_balance=book_balance
        - sum((b.amount for b in book_open), ZERO)
        + sum((ln.amount for ln in stmt_open), ZERO),
    )
