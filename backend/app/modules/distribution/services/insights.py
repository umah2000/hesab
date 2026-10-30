"""What the visitor reads about a customer and about their own work (ADR-0026).

* **History** shows every final invoice of an assigned customer, whoever sold it, labelled
  by channel (this visitor / another visitor / the shop). It is read only.
* **The report** counts only this visitor's own orders: an in-shop sale or another
  visitor's order is never in it. «Ordered» is by the order's time (rejected and cancelled
  left out); «invoiced» is the invoices made from those orders, by the invoice's date.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import jdatetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.accounting.models import DetailAccount, Voucher, VoucherLine
from app.modules.accounting.services.fiscal import MONTHS
from app.modules.distribution.models import (
    SalesOrder,
    SalesOrderLine,
    Visit,
    Visitor,
    VisitorCollection,
    VisitorTarget,
)
from app.modules.distribution.schemas import (
    CustomerAccountOut,
    CustomerHistoryOut,
    FrequentItemOut,
    HistoryInvoiceOut,
    InvoiceDetailOut,
    InvoiceLineOut,
    NamedAmount,
    OpenChequeOut,
    Period,
    ReportFigures,
    ReportOut,
    StatementRowOut,
)
from app.modules.distribution.services import visitors
from app.modules.iam.guard import Actor
from app.modules.iam.models import AppUser
from app.modules.inventory.models import Item, Unit
from app.modules.inventory.services.stock import tehran_today
from app.modules.sales.models import SalesInvoice, SalesInvoiceLine
from app.modules.sales.services import pricing
from app.modules.sales.services.invoices import receivable_balance
from app.modules.treasury.models import Cheque

ZERO = Decimal(0)
TEHRAN = ZoneInfo("Asia/Tehran")
HISTORY_DAYS = 180
HISTORY_LIMIT = 60
STATEMENT_DAYS = 60
NOT_COUNTED = ("rejected", "cancelled")
PENDING = ("submitted", "approved")


def _assigned(s: Session, actor: Actor, customer_id: uuid.UUID) -> Visitor:
    v = visitors.of_actor(s, actor)
    if not visitors.is_assigned(s, v.id, customer_id):
        raise PermissionDeniedError("این مشتری به شما تخصیص داده نشده است", code="not_assigned")
    return v


def _visitor_names(s: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = s.execute(
        select(Visitor.id, AppUser.full_name, AppUser.username)
        .join(AppUser, AppUser.id == Visitor.user_id)
        .where(Visitor.id.in_(ids))
    ).all()
    return {vid: (full or user) for vid, full, user in rows}


def _channels(
    s: Session, me: uuid.UUID, invoice_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str | None]]:
    """Who sold each invoice: this visitor, another visitor (name), or the shop."""
    by_invoice: dict[uuid.UUID, uuid.UUID] = {}
    if invoice_ids:
        for inv_id, vid in s.execute(
            select(SalesOrder.invoice_id, SalesOrder.visitor_id).where(
                SalesOrder.invoice_id.in_(invoice_ids)
            )
        ).all():
            if inv_id is not None:
                by_invoice[inv_id] = vid
    names = _visitor_names(s, set(by_invoice.values()))
    out: dict[uuid.UUID, tuple[str, str | None]] = {}
    for invoice_id in invoice_ids:
        seller = by_invoice.get(invoice_id)
        if seller is None:
            out[invoice_id] = ("shop", None)
        elif seller == me:
            out[invoice_id] = ("mine", None)
        else:
            out[invoice_id] = ("visitor", names.get(seller))
    return out


def history(s: Session, actor: Actor, customer_id: uuid.UUID) -> CustomerHistoryOut:
    v = _assigned(s, actor, customer_id)
    since = tehran_today() - timedelta(days=HISTORY_DAYS)
    invoices = list(
        s.scalars(
            select(SalesInvoice)
            .where(
                SalesInvoice.customer_id == customer_id,
                SalesInvoice.status == "final",
                SalesInvoice.document_date >= since,
            )
            .order_by(SalesInvoice.document_date.desc(), SalesInvoice.number.desc())
            .limit(HISTORY_LIMIT)
        )
    )
    ids = [i.id for i in invoices]
    counts = dict(
        s.execute(
            select(SalesInvoiceLine.invoice_id, func.count())
            .where(SalesInvoiceLine.invoice_id.in_(ids or [uuid.UUID(int=0)]))
            .group_by(SalesInvoiceLine.invoice_id)
        ).all()
    )
    channels = _channels(s, v.id, ids)
    out = [
        HistoryInvoiceOut(
            id=i.id,
            number=i.number,
            kind=i.kind,  # type: ignore[arg-type]
            document_date=i.document_date,
            grand_total=i.grand_total,
            line_count=int(counts.get(i.id, 0)),
            channel=channels[i.id][0],  # type: ignore[arg-type]
            visitor_name=channels[i.id][1],
        )
        for i in invoices
    ]
    freq = s.execute(
        select(
            SalesInvoiceLine.item_id,
            func.count(func.distinct(SalesInvoice.id)),
            func.max(SalesInvoice.document_date),
        )
        .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
        .where(
            SalesInvoice.customer_id == customer_id,
            SalesInvoice.status == "final",
            SalesInvoice.kind == "sale",
            SalesInvoice.document_date >= since,
        )
        .group_by(SalesInvoiceLine.item_id)
        .order_by(func.count(func.distinct(SalesInvoice.id)).desc())
        .limit(10)
    ).all()
    items = {
        i.id: i.name
        for i in s.scalars(
            select(Item).where(Item.id.in_([r[0] for r in freq] or [uuid.UUID(int=0)]))
        )
    }
    return CustomerHistoryOut(
        invoices=out,
        frequent_items=[
            FrequentItemOut(item_id=iid, item_name=items.get(iid, ""), times=int(n), last_date=last)
            for iid, n, last in freq
        ],
    )


def invoice_detail(s: Session, actor: Actor, invoice_id: uuid.UUID) -> InvoiceDetailOut:
    inv = s.get(SalesInvoice, invoice_id)
    if inv is None or inv.status != "final" or inv.customer_id is None:
        raise NotFoundError("فاکتور یافت نشد")
    v = _assigned(s, actor, inv.customer_id)
    lines = list(inv.lines)
    items = {
        i.id: i
        for i in s.scalars(
            select(Item).where(Item.id.in_({ln.item_id for ln in lines} or {uuid.UUID(int=0)}))
        )
    }
    units = {u.id: u.name for u in s.scalars(select(Unit))}
    channel, name = _channels(s, v.id, [inv.id])[inv.id]
    return InvoiceDetailOut(
        id=inv.id,
        number=inv.number,
        kind=inv.kind,  # type: ignore[arg-type]
        document_date=inv.document_date,
        grand_total=inv.grand_total,
        line_count=len(lines),
        channel=channel,  # type: ignore[arg-type]
        visitor_name=name,
        subtotal=inv.subtotal,
        discount_total=inv.discount_total,
        tax_total=inv.tax_total,
        lines=[
            InvoiceLineOut(
                item_id=ln.item_id,
                item_code=items[ln.item_id].code if ln.item_id in items else "",
                item_name=items[ln.item_id].name if ln.item_id in items else "",
                unit_name=units.get(ln.unit_id, ""),
                qty=ln.qty,
                unit_price=ln.unit_price,
                discount=ln.promotion_discount + ln.manual_discount,
                tax=ln.tax,
                line_total=ln.line_total,
            )
            for ln in sorted(lines, key=lambda x: x.line_no)
        ],
    )


def account(s: Session, actor: Actor, customer_id: uuid.UUID) -> CustomerAccountOut:
    v = _assigned(s, actor, customer_id)
    acc = s.get(DetailAccount, customer_id)
    if acc is None:
        raise NotFoundError("مشتری یافت نشد")
    balance = receivable_balance(s, customer_id)
    cheques = list(
        s.scalars(
            select(Cheque)
            .where(
                Cheque.party_id == customer_id,
                Cheque.direction == "received",
                Cheque.status.in_(("in_hand", "deposited")),
            )
            .order_by(Cheque.due_date)
        )
    )
    pending = s.scalar(
        select(func.sum(VisitorCollection.amount)).where(
            VisitorCollection.visitor_id == v.id,
            VisitorCollection.customer_id == customer_id,
            VisitorCollection.status == "pending",
        )
    )
    rows = _statement(s, customer_id, tehran_today() - timedelta(days=STATEMENT_DAYS))
    return CustomerAccountOut(
        balance=balance,
        credit_limit=acc.credit_limit,
        credit_unlimited=acc.credit_unlimited,
        available=acc.credit_limit - balance if acc.credit_limit is not None else None,
        open_cheques=[
            OpenChequeOut(
                number=c.number,
                amount=c.amount,
                due_date=c.due_date,
                status=c.status,
                bank_name=c.bank_name,
            )
            for c in cheques
        ],
        pending_collections=Decimal(pending or 0),
        statement=rows,
    )


def _statement(s: Session, customer_id: uuid.UUID, since: date) -> list[StatementRowOut]:
    """The customer's account since ``since`` with a running balance (final vouchers only).

    Read straight from the vouchers, so a customer without a party row still has one.
    """
    base = (
        select(VoucherLine, Voucher)
        .join(Voucher, Voucher.id == VoucherLine.voucher_id)
        .where(Voucher.status == "final", VoucherLine.detail_account_id == customer_id)
    )
    opening = Decimal(
        s.scalar(
            select(func.sum(VoucherLine.debit - VoucherLine.credit))
            .join(Voucher, Voucher.id == VoucherLine.voucher_id)
            .where(
                Voucher.status == "final",
                VoucherLine.detail_account_id == customer_id,
                Voucher.document_date < since,
            )
        )
        or 0
    )
    found = list(
        s.execute(
            base.where(Voucher.document_date >= since).order_by(
                Voucher.document_date, Voucher.number, VoucherLine.line_no
            )
        ).all()
    )
    running = opening
    rows = []
    for ln, v in found:
        running += ln.debit - ln.credit
        rows.append(
            StatementRowOut(
                document_date=v.document_date,
                description=ln.description or v.description,
                debit=ln.debit,
                credit=ln.credit,
                balance=running,
            )
        )
    return rows[-50:]


# --- the visitor's own report ----------------------------------------------------------


def _jmonth(d: date) -> tuple[int, int]:
    j = jdatetime.date.fromgregorian(date=d)
    return j.year, j.month


def _month_range(jy: int, jm: int) -> tuple[date, date]:
    start = jdatetime.date(jy, jm, 1).togregorian()
    nxt = jdatetime.date(jy + (jm == 12), jm % 12 + 1, 1).togregorian()
    return start, nxt - timedelta(days=1)


def period_range(period: Period, day: date) -> tuple[date, date]:
    if period == "day":
        return day, day
    if period == "week":  # the Iranian week starts on Saturday
        start = day - timedelta(days=(day.weekday() - 5) % 7)
        return start, start + timedelta(days=6)
    return _month_range(*_jmonth(day))


def _previous(period: Period, start: date) -> tuple[date, date]:
    if period == "day":
        d = start - timedelta(days=1)
        return d, d
    if period == "week":
        return start - timedelta(days=7), start - timedelta(days=1)
    return period_range("month", start - timedelta(days=1))


def _label(period: Period, start: date, end: date) -> str:
    j = jdatetime.date.fromgregorian(date=start)
    if period == "day":
        return f"{j.year}/{j.month:02d}/{j.day:02d}"
    if period == "week":
        e = jdatetime.date.fromgregorian(date=end)
        return f"{j.month:02d}/{j.day:02d} تا {e.month:02d}/{e.day:02d}"
    return f"{MONTHS[j.month - 1]} {j.year}"


def _utc(d: date) -> datetime:
    return datetime.combine(d, time.min, TEHRAN).astimezone(UTC)


def _invoiced(s: Session, visitor_id: uuid.UUID, start: date, end: date) -> tuple[Decimal, int]:
    total, count = s.execute(
        select(func.sum(SalesInvoice.grand_total), func.count())
        .join(SalesOrder, SalesOrder.invoice_id == SalesInvoice.id)
        .where(
            SalesOrder.visitor_id == visitor_id,
            SalesInvoice.status == "final",
            SalesInvoice.document_date >= start,
            SalesInvoice.document_date <= end,
        )
    ).one()
    return Decimal(total or 0), int(count or 0)


def _figures(s: Session, visitor_id: uuid.UUID, start: date, end: date) -> ReportFigures:
    lo, hi = _utc(start), _utc(end + timedelta(days=1))
    in_period = (
        SalesOrder.visitor_id == visitor_id,
        SalesOrder.ordered_at >= lo,
        SalesOrder.ordered_at < hi,
    )
    by_status = dict(
        s.execute(
            select(SalesOrder.status, func.count()).where(*in_period).group_by(SalesOrder.status)
        ).all()
    )
    total, count, customers = s.execute(
        select(
            func.sum(SalesOrder.grand_total),
            func.count(),
            func.count(func.distinct(SalesOrder.customer_id)),
        ).where(*in_period, SalesOrder.status.not_in(NOT_COUNTED))
    ).one()
    invoiced, invoiced_count = _invoiced(s, visitor_id, start, end)
    visits = dict(
        s.execute(
            select(Visit.outcome, func.count())
            .where(Visit.visitor_id == visitor_id, Visit.visited_at >= lo, Visit.visited_at < hi)
            .group_by(Visit.outcome)
        ).all()
    )
    ordered = Decimal(total or 0)
    count = int(count or 0)
    return ReportFigures(
        ordered_amount=ordered,
        ordered_count=count,
        invoiced_amount=invoiced,
        invoiced_count=invoiced_count,
        customers=int(customers or 0),
        average_order=pricing.rial(ordered / count) if count else ZERO,
        rejected_count=int(by_status.get("rejected", 0)),
        pending_count=sum(int(by_status.get(k, 0)) for k in PENDING),
        visits=sum(int(n) for n in visits.values()),
        no_order_reasons={k: int(n) for k, n in visits.items() if k != "order"},
    )


def report(s: Session, actor: Actor, period: Period, day: date | None) -> ReportOut:
    v = visitors.of_actor(s, actor)
    start, end = period_range(period, day or tehran_today())
    p_start, p_end = _previous(period, start)
    lo, hi = _utc(start), _utc(end + timedelta(days=1))
    counted = (
        SalesOrder.visitor_id == v.id,
        SalesOrder.ordered_at >= lo,
        SalesOrder.ordered_at < hi,
        SalesOrder.status.not_in(NOT_COUNTED),
    )
    top_c = s.execute(
        select(SalesOrder.customer_id, func.sum(SalesOrder.grand_total), func.count())
        .where(*counted)
        .group_by(SalesOrder.customer_id)
        .order_by(func.sum(SalesOrder.grand_total).desc())
        .limit(5)
    ).all()
    names = {
        d.id: d.name
        for d in s.scalars(
            select(DetailAccount).where(
                DetailAccount.id.in_([r[0] for r in top_c] or [uuid.UUID(int=0)])
            )
        )
    }
    top_i = s.execute(
        select(
            SalesOrderLine.item_id,
            func.sum(SalesOrderLine.line_total),
            func.count(func.distinct(SalesOrder.id)),
        )
        .join(SalesOrder, SalesOrder.id == SalesOrderLine.order_id)
        .where(*counted)
        .group_by(SalesOrderLine.item_id)
        .order_by(func.sum(SalesOrderLine.line_total).desc())
        .limit(5)
    ).all()
    items = {
        i.id: i.name
        for i in s.scalars(
            select(Item).where(Item.id.in_([r[0] for r in top_i] or [uuid.UUID(int=0)]))
        )
    }
    jy, jm = _jmonth(start)
    target = s.scalar(
        select(VisitorTarget.amount).where(
            VisitorTarget.visitor_id == v.id,
            VisitorTarget.jalali_year == jy,
            VisitorTarget.jalali_month == jm,
        )
    )
    progress = None
    if target is not None:
        progress = _invoiced(s, v.id, *_month_range(jy, jm))[0]
    return ReportOut(
        period=period,
        start=start,
        end=end,
        label=_label(period, start, end),
        current=_figures(s, v.id, start, end),
        previous=_figures(s, v.id, p_start, p_end),
        top_customers=[
            NamedAmount(id=cid, name=names.get(cid, ""), amount=Decimal(t or 0), count=int(n))
            for cid, t, n in top_c
        ],
        top_items=[
            NamedAmount(id=iid, name=items.get(iid, ""), amount=Decimal(t or 0), count=int(n))
            for iid, t, n in top_i
        ],
        target=target,
        target_progress=progress,
    )
