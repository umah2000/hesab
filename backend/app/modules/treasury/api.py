"""Treasury endpoints (/api/v1/treasury): money accounts, receipts, payments, transfers,
card settlements, cheques, bank statements and reconciliation."""

from __future__ import annotations

from datetime import date
from typing import Literal

from flask import Blueprint, Response
from flask.typing import ResponseReturnValue
from pydantic import BaseModel, Field

from app.core import excel
from app.core.db import new_session, unit_of_work
from app.core.http import if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.openapi import doc
from app.modules.iam.guard import current_actor, require
from app.modules.inventory.services.stock import tehran_today
from app.modules.treasury.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountUpdateIn,
    AutoMatchOut,
    BookLineOut,
    ChequeActionIn,
    ChequeOut,
    ChequeQuery,
    ChequeSummary,
    DocumentOut,
    DocumentQuery,
    DocumentSummary,
    MatchIn,
    ReceiptIn,
    ReconciliationOut,
    ReverseIn,
    SettlementIn,
    StatementImportOut,
    StatementLineOut,
    StatementQuery,
    TransferIn,
)
from app.modules.treasury.services import accounts, cheques, documents, statements

bp = Blueprint("treasury", __name__)
PERM = "treasury.manage"


# --- accounts ---------------------------------------------------------------


class AccountQuery(BaseModel):
    kind: Literal["cash", "bank"] | None = None


@bp.get("/accounts")
@require(PERM)
@doc("صندوق‌ها و حساب‌های بانکی با مانده", query=AccountQuery, response=[AccountOut])
def list_accounts() -> ResponseReturnValue:
    q = parse_query(AccountQuery)
    s = new_session()
    try:
        return to_json(list(accounts.list_accounts(s, current_actor(), q.kind)))
    finally:
        s.close()


@bp.post("/accounts")
@require(PERM)
@doc("تعریف صندوق یا حساب بانکی", body=AccountCreateIn, response=AccountOut, idempotent=True)
def create_account() -> ResponseReturnValue:
    data = parse_body(AccountCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: accounts.create(s, actor, data))


@bp.put("/accounts/<account_id>")
@require(PERM)
@doc("ویرایش صندوق یا حساب بانکی", body=AccountUpdateIn, response=AccountOut, versioned=True)
def update_account(account_id: str) -> ResponseReturnValue:
    data = parse_body(AccountUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(accounts.update(s, current_actor(), parse_uuid(account_id), data, version))


# --- documents --------------------------------------------------------------


@bp.get("/documents")
@require(PERM)
@doc("اسناد دریافت، پرداخت، انتقال و تسویه", query=DocumentQuery, response=DocumentSummary)
def list_documents() -> ResponseReturnValue:
    q = parse_query(DocumentQuery)
    s = new_session()
    try:
        return to_json(documents.list_documents(s, current_actor(), q))
    finally:
        s.close()


@bp.get("/documents/<doc_id>")
@require(PERM)
@doc("جزئیات سند خزانه", response=DocumentOut)
def get_document(doc_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(documents.get(s, current_actor(), parse_uuid(doc_id)))
    finally:
        s.close()


@bp.post("/receipts")
@require(PERM)
@doc("دریافت از طرف‌حساب (نقد، بانک، چک)", body=ReceiptIn, response=DocumentOut, idempotent=True)
def create_receipt() -> ResponseReturnValue:
    data = parse_body(ReceiptIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: documents.create_receipt(s, actor, data))


@bp.post("/payments")
@require(PERM)
@doc("پرداخت به طرف‌حساب (نقد، بانک، چک)", body=ReceiptIn, response=DocumentOut, idempotent=True)
def create_payment() -> ResponseReturnValue:
    data = parse_body(ReceiptIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: documents.create_payment(s, actor, data))


@bp.post("/transfers")
@require(PERM)
@doc("انتقال وجه بین صندوق و بانک", body=TransferIn, response=DocumentOut, idempotent=True)
def create_transfer() -> ResponseReturnValue:
    data = parse_body(TransferIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: documents.create_transfer(s, actor, data))


@bp.post("/settlements")
@require(PERM)
@doc("تسویه کارت‌خوان به حساب بانک", body=SettlementIn, response=DocumentOut, idempotent=True)
def create_settlement() -> ResponseReturnValue:
    data = parse_body(SettlementIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: documents.create_settlement(s, actor, data))


@bp.post("/documents/<doc_id>/reverse")
@require(PERM)
@doc("برگشت سند خزانه با سند حسابداری معکوس", body=ReverseIn, response=DocumentOut, versioned=True)
def reverse_document(doc_id: str) -> ResponseReturnValue:
    data = parse_body(ReverseIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(documents.reverse(s, current_actor(), parse_uuid(doc_id), data, version))


# --- cheques ----------------------------------------------------------------


@bp.get("/cheques")
@require(PERM)
@doc("چک‌های دریافتی و پرداختی", query=ChequeQuery, response=ChequeSummary)
def list_cheques() -> ResponseReturnValue:
    q = parse_query(ChequeQuery)
    s = new_session()
    try:
        return to_json(cheques.list_cheques(s, current_actor(), q, tehran_today()))
    finally:
        s.close()


@bp.get("/cheques/<cheque_id>")
@require(PERM)
@doc("جزئیات و سابقه چک", response=ChequeOut)
def get_cheque(cheque_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(cheques.get(s, current_actor(), parse_uuid(cheque_id)))
    finally:
        s.close()


@bp.post("/cheques/<cheque_id>/actions")
@require(PERM)
@doc(
    "تغییر وضعیت چک (واگذاری، وصول، برگشت…)",
    body=ChequeActionIn,
    response=ChequeOut,
    versioned=True,
)
def cheque_action(cheque_id: str) -> ResponseReturnValue:
    data = parse_body(ChequeActionIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(cheques.act(s, current_actor(), parse_uuid(cheque_id), data, version))


# --- bank statements ----------------------------------------------------------


@bp.get("/statements/template")
@require(PERM)
@doc("قالب Excel صورتحساب بانک")
def statement_template() -> ResponseReturnValue:
    return Response(
        statements.template(),
        mimetype=excel.XLSX,
        headers={"Content-Disposition": "attachment; filename=nextcam-bank-statement.xlsx"},
    )


@bp.post("/accounts/<account_id>/statement/preview")
@require(PERM)
@doc("پیش‌نمایش ورود صورتحساب بانک", response=StatementImportOut)
def statement_preview(account_id: str) -> ResponseReturnValue:
    data = excel.upload_bytes()
    s = new_session()
    try:
        return to_json(statements.preview(s, current_actor(), parse_uuid(account_id), data))
    finally:
        s.close()


@bp.post("/accounts/<account_id>/statement/commit")
@require(PERM)
@doc("ورود صورتحساب بانک (ردیف‌های تکراری نادیده)", response=StatementImportOut, idempotent=True)
def statement_commit(account_id: str) -> ResponseReturnValue:
    data = excel.upload_bytes()
    actor = current_actor()
    aid = parse_uuid(account_id)
    with unit_of_work() as s:
        return idempotent(
            s,
            actor.user_id,
            lambda: statements.commit(s, actor, aid, data),
            status=201,
            body=data + str(aid).encode(),
        )


@bp.get("/accounts/<account_id>/statement")
@require(PERM)
@doc("ردیف‌های صورتحساب بانک", query=StatementQuery, response=StatementLineOut)
def statement_lines(account_id: str) -> ResponseReturnValue:
    q = parse_query(StatementQuery)
    s = new_session()
    try:
        return to_json(statements.list_lines(s, current_actor(), parse_uuid(account_id), q))
    finally:
        s.close()


@bp.post("/accounts/<account_id>/statement/auto-match")
@require(PERM)
@doc("تطبیق خودکار صورتحساب با دفاتر", response=AutoMatchOut)
def statement_auto_match(account_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(statements.auto_match(s, current_actor(), parse_uuid(account_id)))


class ReconQuery(BaseModel):
    as_of: date = Field(default_factory=tehran_today)


@bp.get("/accounts/<account_id>/reconciliation")
@require(PERM)
@doc("مغایرت‌گیری بانکی", query=ReconQuery, response=ReconciliationOut)
def reconciliation(account_id: str) -> ResponseReturnValue:
    q = parse_query(ReconQuery)
    s = new_session()
    try:
        return to_json(
            statements.reconciliation(s, current_actor(), parse_uuid(account_id), q.as_of)
        )
    finally:
        s.close()


@bp.get("/statement-lines/<line_id>/candidates")
@require(PERM)
@doc("ردیف‌های سند هم‌مبلغ برای تطبیق دستی", response=[BookLineOut])
def statement_candidates(line_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(statements.candidates(s, current_actor(), parse_uuid(line_id))))
    finally:
        s.close()


@bp.post("/statement-lines/<line_id>/match")
@require(PERM)
@doc("تطبیق دستی ردیف صورتحساب", body=MatchIn, response=StatementLineOut)
def statement_match(line_id: str) -> ResponseReturnValue:
    data = parse_body(MatchIn)
    with unit_of_work() as s:
        return to_json(
            statements.match(s, current_actor(), parse_uuid(line_id), data.voucher_line_id)
        )


@bp.post("/statement-lines/<line_id>/unmatch")
@require(PERM)
@doc("لغو تطبیق ردیف صورتحساب", response=StatementLineOut)
def statement_unmatch(line_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(statements.unmatch(s, current_actor(), parse_uuid(line_id)))
