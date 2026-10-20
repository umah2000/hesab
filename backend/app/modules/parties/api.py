"""Counterparty endpoints (/api/v1/parties)."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, Response, request
from flask.typing import ResponseReturnValue
from pydantic import BaseModel, Field

from app.core import excel
from app.core.db import new_session, unit_of_work
from app.core.excel import ImportPreview, ImportResult
from app.core.http import if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.openapi import doc
from app.modules.iam.guard import current_actor, require, require_any
from app.modules.inventory.services.stock import tehran_today
from app.modules.organization.models import Organization
from app.modules.parties.schemas import (
    GroupIn,
    GroupOut,
    NoteIn,
    NoteOut,
    PartyCreateIn,
    PartyOut,
    PartyQuery,
    PartySummary,
    PartyUpdateIn,
    StatementOut,
)
from app.modules.parties.services import core, importer

bp = Blueprint("parties", __name__)
VIEW = ("parties.view", "parties.manage")


@bp.get("")
@require_any(*VIEW)
@doc("فهرست طرف‌حساب‌ها با مانده", query=PartyQuery, response=PartySummary)
def list_parties() -> ResponseReturnValue:
    q = parse_query(PartyQuery)
    s = new_session()
    try:
        return to_json(core.list_parties(s, current_actor(), q))
    finally:
        s.close()


@bp.post("")
@require("parties.manage")
@doc("تعریف طرف‌حساب", body=PartyCreateIn, response=PartyOut, idempotent=True)
def create() -> ResponseReturnValue:
    data = parse_body(PartyCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: core.create(s, actor, data))


@bp.get("/<party_id>")
@require_any(*VIEW)
@doc("جزئیات طرف‌حساب (اطلاعات حساس بدون parties.manage پوشیده)", response=PartyOut)
def get(party_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(core.get(s, current_actor(), parse_uuid(party_id)))
    finally:
        s.close()


@bp.put("/<party_id>")
@require("parties.manage")
@doc("ویرایش طرف‌حساب", body=PartyUpdateIn, response=PartyOut, versioned=True)
def update(party_id: str) -> ResponseReturnValue:
    data = parse_body(PartyUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(core.update(s, current_actor(), parse_uuid(party_id), data, version))


class StatementQuery(BaseModel):
    date_from: date | None = None
    date_to: date | None = None


@bp.get("/<party_id>/statement")
@require_any(*VIEW)
@doc("گردش و مانده طرف‌حساب (اسناد قطعی)", query=StatementQuery, response=StatementOut)
def statement(party_id: str) -> ResponseReturnValue:
    q = parse_query(StatementQuery)
    s = new_session()
    try:
        return to_json(core.statement(s, parse_uuid(party_id), q.date_from, q.date_to))
    finally:
        s.close()


@bp.get("/<party_id>/notes")
@require_any(*VIEW)
@doc("یادداشت‌ها و پیگیری‌ها", response=[NoteOut])
def notes(party_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(core.notes(s, parse_uuid(party_id))))
    finally:
        s.close()


@bp.post("/<party_id>/notes")
@require_any(*VIEW)
@doc("افزودن یادداشت یا پیگیری", body=NoteIn, response=NoteOut)
def add_note(party_id: str) -> ResponseReturnValue:
    data = parse_body(NoteIn)
    with unit_of_work() as s:
        return to_json(core.add_note(s, current_actor(), parse_uuid(party_id), data), 201)


class DoneIn(BaseModel):
    done: bool = True


@bp.post("/notes/<note_id>/done")
@require_any(*VIEW)
@doc("انجام شدن پیگیری", body=DoneIn, response=NoteOut)
def note_done(note_id: str) -> ResponseReturnValue:
    data = parse_body(DoneIn)
    with unit_of_work() as s:
        return to_json(core.set_note_done(s, parse_uuid(note_id), data.done))


class FollowQuery(BaseModel):
    until: date | None = None


@bp.get("/follow-ups")
@require_any(*VIEW)
@doc("پیگیری‌های سررسیده", query=FollowQuery, response=[NoteOut])
def follow_ups() -> ResponseReturnValue:
    q = parse_query(FollowQuery)
    s = new_session()
    try:
        return to_json(list(core.due_follow_ups(s, q.until or tehran_today())))
    finally:
        s.close()


@bp.get("/groups")
@require_any(*VIEW)
@doc("گروه‌های طرف‌حساب", response=[GroupOut])
def groups() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(core.list_groups(s)))
    finally:
        s.close()


@bp.post("/groups")
@require("parties.manage")
@doc("تعریف گروه طرف‌حساب", body=GroupIn, response=GroupOut)
def create_group() -> ResponseReturnValue:
    data = parse_body(GroupIn)
    with unit_of_work() as s:
        return to_json(core.create_group(s, current_actor(), data), 201)


# --- Excel import -----------------------------------------------------------------


def _currency() -> str:
    s = new_session()
    try:
        org = s.query(Organization).first()
        return org.display_currency if org else "IRT"
    finally:
        s.close()


@bp.get("/import/template")
@require("import.run")
@doc("قالب Excel طرف‌حساب‌ها")
def import_template() -> ResponseReturnValue:
    return Response(
        importer.template(_currency()),
        mimetype=excel.XLSX,
        headers={"Content-Disposition": "attachment; filename=nextcam-parties.xlsx"},
    )


@bp.post("/import/preview")
@require("import.run")
@doc("پیش‌نمایش ورود طرف‌حساب‌ها", response=ImportPreview)
def import_preview() -> ResponseReturnValue:
    data = excel.upload_bytes()
    s = new_session()
    try:
        return to_json(importer.preview(s, data, _currency()))
    finally:
        s.close()


class ImportForm(BaseModel):
    opening_date: date = Field(default_factory=tehran_today)


@bp.post("/import/commit")
@require("import.run")
@doc("ورود طرف‌حساب‌ها؛ مانده‌ها در سند افتتاحیه پیش‌نویس", response=ImportResult, idempotent=True)
def import_commit() -> ResponseReturnValue:
    data = excel.upload_bytes()
    form = ImportForm.model_validate(request.form.to_dict())
    actor = current_actor()
    if not actor.has("parties.manage"):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("ورود طرف‌حساب نیازمند مجوز «مدیریت طرف‌حساب‌ها» است")
    cur = _currency()
    with unit_of_work() as s:
        return idempotent(
            s,
            actor.user_id,
            lambda: importer.commit(s, actor, data, cur, form.opening_date),
            status=201,
            body=data + form.model_dump_json().encode(),
        )
