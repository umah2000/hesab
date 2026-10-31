"""Inventory endpoints."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from typing import ParamSpec, TypeVar

from flask import Blueprint, Response, request
from flask.typing import ResponseReturnValue
from pydantic import BaseModel, Field

from app.core import excel
from app.core.db import new_session, unit_of_work
from app.core.errors import DomainError
from app.core.excel import ImportPreview, ImportResult
from app.core.http import if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.openapi import doc
from app.modules.iam.guard import current_actor, require, require_any
from app.modules.inventory.models import Warehouse
from app.modules.inventory.schemas import (
    BalanceRow,
    GroupIn,
    GroupOut,
    ImageOrderIn,
    ItemImageOut,
    ItemIn,
    ItemOut,
    ItemQuery,
    ItemSummary,
    KardexRow,
    LookupOut,
    LotRow,
    PriceListOut,
    ScaleRuleIn,
    ScaleRuleOut,
    StockDocIn,
    StockDocOut,
    StockDocSummary,
    UnitOut,
    WarehouseIn,
    WarehouseOut,
)
from app.modules.inventory.services import catalog, images, importer, stock
from app.modules.organization.models import Organization

P = ParamSpec("P")
R = TypeVar("R")

bp = Blueprint("inventory", __name__)

READ = (
    "inventory.item.manage",
    "inventory.stock.create",
    "inventory.stock.adjust",
    "inventory.report.view",
    "inventory.price.manage",
    "sales.pos.use",
    "import.run",
)


def _read(fn: Callable[P, R]) -> Callable[P, R]:
    return require_any(*READ)(fn)


def _currency(s: object) -> str:
    from sqlalchemy import select

    org = s.scalar(select(Organization))  # type: ignore[attr-defined]
    return org.display_currency if org else "IRT"


# --- catalog ----------------------------------------------------------------


@bp.get("/units")
@_read
@doc("واحدهای اندازه‌گیری", response=[UnitOut])
def list_units() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(catalog.list_units(s)))
    finally:
        s.close()


@bp.get("/groups")
@_read
@doc("گروه‌های کالا", response=[GroupOut])
def list_groups() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(catalog.list_groups(s)))
    finally:
        s.close()


@bp.post("/groups")
@require("inventory.item.manage")
@doc("ایجاد گروه کالا", body=GroupIn, response=GroupOut, idempotent=True)
def create_group() -> ResponseReturnValue:
    data = parse_body(GroupIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: catalog.create_group(s, actor, data))


@bp.get("/price-lists")
@_read
@doc("لیست‌های قیمت", response=[PriceListOut])
def list_price_lists() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(catalog.list_price_lists(s)))
    finally:
        s.close()


@bp.get("/items")
@_read
@doc("فهرست کالاها (جست‌وجو با کد، نام یا بارکد)", query=ItemQuery, response=ItemSummary)
def list_items() -> ResponseReturnValue:
    q = parse_query(ItemQuery)
    s = new_session()
    try:
        return to_json(catalog.list_items(s, q))
    finally:
        s.close()


@bp.get("/items/<item_id>")
@_read
@doc("جزئیات کالا", response=ItemOut)
def get_item(item_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(catalog.item_out(s, parse_uuid(item_id)))
    finally:
        s.close()


@bp.get("/items/<item_id>/lots")
@_read
@doc("دسته‌های کالا با تاریخ انقضا", response=[LotRow])
def item_lots(item_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list[BaseModel](stock.item_lots(s, current_actor(), parse_uuid(item_id))))
    finally:
        s.close()


def _check_price_permission(data: ItemIn) -> None:
    actor = current_actor()
    if data.prices and not actor.has("inventory.price.manage"):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("تعیین قیمت نیازمند مجوز «مدیریت قیمت‌ها» است")


@bp.post("/items")
@require("inventory.item.manage")
@doc("تعریف کالا", body=ItemIn, response=ItemOut, idempotent=True)
def create_item() -> ResponseReturnValue:
    data = parse_body(ItemIn)
    _check_price_permission(data)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: catalog.create_item(s, actor, data))


@bp.put("/items/<item_id>")
@require("inventory.item.manage")
@doc("ویرایش کالا", body=ItemIn, response=ItemOut, versioned=True)
def update_item(item_id: str) -> ResponseReturnValue:
    data = parse_body(ItemIn)
    version = if_match()
    actor = current_actor()
    with unit_of_work() as s:
        if not actor.has("inventory.price.manage"):
            # Without price permission the stored prices are kept as they are.
            current = catalog.item_out(s, parse_uuid(item_id))
            data = data.model_copy(update={"prices": current.prices})
        return to_json(catalog.update_item(s, actor, parse_uuid(item_id), data, version))


class LookupQuery(BaseModel):
    barcode: str = Field(min_length=1, max_length=64)
    price_list_id: uuid.UUID | None = None


@bp.get("/items/<item_id>/images")
@_read
@doc("عکس‌های کالا (اولی عکس اصلی)", response=[ItemImageOut])
def list_item_images(item_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(images.list_images(s, parse_uuid(item_id))))
    finally:
        s.close()


@bp.post("/items/<item_id>/images")
@require("inventory.item.manage")
@doc("افزودن عکس کالا (multipart، فیلد file؛ JPEG/PNG/WebP تا ۱۵MB)", response=ItemImageOut)
def add_item_image(item_id: str) -> ResponseReturnValue:
    request.max_content_length = images.MAX_UPLOAD + 64 * 1024
    f = request.files.get("file")
    if f is None:
        raise DomainError("فایل عکس را انتخاب کنید", code="file_required")
    data = f.read()
    with unit_of_work() as s:
        return to_json(images.add(s, current_actor(), parse_uuid(item_id), data)), 201


@bp.put("/items/<item_id>/images/order")
@require("inventory.item.manage")
@doc("ترتیب عکس‌های کالا؛ اولی عکس اصلی می‌شود", body=ImageOrderIn, response=[ItemImageOut])
def order_item_images(item_id: str) -> ResponseReturnValue:
    data = parse_body(ImageOrderIn)
    with unit_of_work() as s:
        return to_json(list(images.reorder(s, current_actor(), parse_uuid(item_id), data.ids)))


@bp.delete("/items/<item_id>/images/<image_id>")
@require("inventory.item.manage")
@doc("حذف عکس کالا")
def delete_item_image(item_id: str, image_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        images.remove(s, current_actor(), parse_uuid(item_id), parse_uuid(image_id))
    return "", 204


@bp.get("/images/<image_id>")
@_read
@doc("فایل عکس کالا (size=thumb|large؛ JPEG)")
def item_image_file(image_id: str) -> ResponseReturnValue:
    return image_response(parse_uuid(image_id), request.args.get("size", "thumb"))


def image_response(image_id: uuid.UUID, size: str) -> Response:
    """JPEG with a long private cache: an image id never changes content (ADR-0022)."""
    s = new_session()
    try:
        data, etag = images.content(s, image_id, size)
    finally:
        s.close()
    resp = Response(data, mimetype="image/jpeg")
    resp.set_etag(etag)
    resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    resp.make_conditional(request)
    return resp


@bp.get("/items/lookup")
@require_any("sales.pos.use", "inventory.item.manage", "inventory.stock.create")
@doc(
    "جست‌وجوی یک اسکن: بارکد، بارکد بسته، بارکد ترازو یا کد کالا",
    query=LookupQuery,
    response=LookupOut,
)
def lookup() -> ResponseReturnValue:
    q = parse_query(LookupQuery)
    s = new_session()
    try:
        return to_json(catalog.lookup(s, q.barcode, q.price_list_id))
    finally:
        s.close()


@bp.get("/scale-rules")
@_read
@doc("قواعد بارکد ترازو", response=[ScaleRuleOut])
def list_scale_rules() -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(list(catalog.list_scale_rules(s)))
    finally:
        s.close()


@bp.post("/scale-rules")
@require("inventory.item.manage")
@doc("تعریف قاعده بارکد ترازو", body=ScaleRuleIn, response=ScaleRuleOut, idempotent=True)
def create_scale_rule() -> ResponseReturnValue:
    data = parse_body(ScaleRuleIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: catalog.save_scale_rule(s, actor, data))


@bp.put("/scale-rules/<rule_id>")
@require("inventory.item.manage")
@doc("ویرایش قاعده بارکد ترازو", body=ScaleRuleIn, response=ScaleRuleOut, versioned=True)
def update_scale_rule(rule_id: str) -> ResponseReturnValue:
    data = parse_body(ScaleRuleIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(
            catalog.save_scale_rule(s, current_actor(), data, parse_uuid(rule_id), version)
        )


# --- warehouses -------------------------------------------------------------


def _wh_out(w: Warehouse) -> WarehouseOut:
    from app.core.db import version_to_str

    return WarehouseOut(
        id=w.id,
        branch_id=w.branch_id,
        code=w.code,
        name=w.name,
        is_active=w.is_active,
        row_version=version_to_str(w.row_version),
    )


@bp.get("/warehouses")
@_read
@doc("انبارها در محدوده کاربر", response=[WarehouseOut])
def list_warehouses() -> ResponseReturnValue:
    from sqlalchemy import select

    actor = current_actor()
    s = new_session()
    try:
        stmt = select(Warehouse).order_by(Warehouse.code)
        if actor.branch_ids is not None:
            stmt = stmt.where(Warehouse.branch_id.in_(actor.branch_ids or {uuid.UUID(int=0)}))
        return to_json([_wh_out(w) for w in s.scalars(stmt)])
    finally:
        s.close()


@bp.post("/warehouses")
@require("branches.manage")
@doc("ایجاد انبار", body=WarehouseIn, response=WarehouseOut, idempotent=True)
def create_warehouse() -> ResponseReturnValue:
    data = parse_body(WarehouseIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(
            s,
            actor.user_id,
            lambda: _wh_out(stock.create_warehouse(s, actor, data.branch_id, data.code, data.name)),
        )


# --- stock documents --------------------------------------------------------


class DocQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    doc_type: str | None = Field(default=None, pattern=r"^(opening|adjustment|transfer|count)$")
    status: str | None = Field(default=None, pattern=r"^(draft|final)$")
    warehouse_id: uuid.UUID | None = None


@bp.get("/stock-documents")
@_read
@doc("اسناد انبار", query=DocQuery, response=StockDocSummary)
def list_docs() -> ResponseReturnValue:
    q = parse_query(DocQuery)
    s = new_session()
    try:
        return to_json(
            stock.list_docs(
                s, current_actor(), q.page, q.page_size, q.doc_type, q.status, q.warehouse_id
            )
        )
    finally:
        s.close()


@bp.get("/stock-documents/<doc_id>")
@_read
@doc("جزئیات سند انبار", response=StockDocOut)
def get_doc(doc_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(stock.doc_out(s, stock.get_doc(s, current_actor(), parse_uuid(doc_id))))
    finally:
        s.close()


@bp.post("/stock-documents")
@require("inventory.stock.create")
@doc("ثبت سند انبار پیش‌نویس", body=StockDocIn, response=StockDocOut, idempotent=True)
def create_doc() -> ResponseReturnValue:
    data = parse_body(StockDocIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: stock.create_doc(s, actor, data))


@bp.put("/stock-documents/<doc_id>")
@require("inventory.stock.create")
@doc("ویرایش سند انبار پیش‌نویس", body=StockDocIn, response=StockDocOut, versioned=True)
def update_doc(doc_id: str) -> ResponseReturnValue:
    data = parse_body(StockDocIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(stock.update_doc(s, current_actor(), parse_uuid(doc_id), data, version))


@bp.delete("/stock-documents/<doc_id>")
@require("inventory.stock.create")
@doc("حذف سند انبار پیش‌نویس", versioned=True)
def delete_doc(doc_id: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        stock.delete_doc(s, current_actor(), parse_uuid(doc_id), version)
    return to_json({"status": "ok"})


@bp.post("/stock-documents/<doc_id>/finalize")
@require("inventory.stock.create")
@doc(
    "قطعی کردن سند انبار (گردش موجودی + سند حسابداری در یک تراکنش)",
    response=StockDocOut,
    versioned=True,
)
def finalize_doc(doc_id: str) -> ResponseReturnValue:
    version = if_match()
    with unit_of_work() as s:
        return to_json(stock.finalize_doc(s, current_actor(), parse_uuid(doc_id), version))


# --- reports ----------------------------------------------------------------


class BalanceQuery(BaseModel):
    warehouse_id: uuid.UUID | None = None
    q: str | None = Field(default=None, max_length=60)
    below_min: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


@bp.get("/balances")
@require_any("inventory.report.view", "inventory.stock.create", "inventory.item.manage")
@doc("موجودی و ارزش کالاها", query=BalanceQuery, response=BalanceRow)
def balances() -> ResponseReturnValue:
    q = parse_query(BalanceQuery)
    actor = current_actor()
    s = new_session()
    try:
        page = stock.balances(s, actor, q.warehouse_id, q.q, q.below_min, q.page, q.page_size)
        body = page.model_dump(mode="json")
        body["total_value"] = format(stock.total_value(s, actor, q.warehouse_id), "f")
        return to_json(body)
    finally:
        s.close()


class KardexQuery(BaseModel):
    item_id: uuid.UUID
    warehouse_id: uuid.UUID
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=500)


@bp.get("/kardex")
@require_any("inventory.report.view", "inventory.stock.create")
@doc("کاردکس کالا", query=KardexQuery, response=KardexRow)
def kardex() -> ResponseReturnValue:
    q = parse_query(KardexQuery)
    s = new_session()
    try:
        return to_json(
            stock.kardex(s, current_actor(), q.item_id, q.warehouse_id, q.page, q.page_size)
        )
    finally:
        s.close()


# --- Excel import -----------------------------------------------------------

XLSX = excel.XLSX
_upload = excel.upload_bytes


@bp.get("/import/<kind>/template")
@require("import.run")
@doc("دانلود قالب Excel (items یا opening)")
def import_template(kind: str) -> ResponseReturnValue:
    s = new_session()
    try:
        cur = _currency(s)
    finally:
        s.close()
    if kind not in ("items", "opening"):
        raise DomainError("نوع ورود نامعتبر است", code="invalid_kind")
    content = importer.items_template(cur) if kind == "items" else importer.opening_template(cur)
    name = "nextcam-items.xlsx" if kind == "items" else "nextcam-opening-stock.xlsx"
    return Response(
        content, mimetype=XLSX, headers={"Content-Disposition": f"attachment; filename={name}"}
    )


@bp.post("/import/items/preview")
@require("import.run")
@doc("پیش‌نمایش ورود کالاها (بدون ذخیره)", response=ImportPreview)
def import_items_preview() -> ResponseReturnValue:
    data = _upload()
    s = new_session()
    try:
        return to_json(importer.preview_items(s, data, _currency(s)))
    finally:
        s.close()


@bp.post("/import/items/commit")
@require("import.run")
@doc("ورود کالاها (همه یا هیچ)", response=ImportResult, idempotent=True)
def import_items_commit() -> ResponseReturnValue:
    data = _upload()
    actor = current_actor()
    if not actor.has("inventory.price.manage"):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("ورود کالا با قیمت نیازمند مجوز «مدیریت قیمت‌ها» است")
    with unit_of_work() as s:
        return idempotent(
            s,
            actor.user_id,
            lambda: importer.commit_items(s, actor, data, _currency(s)),
            status=201,
            body=data,
        )


class OpeningForm(BaseModel):
    warehouse_id: uuid.UUID
    document_date: date


@bp.post("/import/opening/preview")
@require("import.run")
@doc("پیش‌نمایش ورود موجودی اول دوره", response=ImportPreview)
def import_opening_preview() -> ResponseReturnValue:
    data = _upload()
    s = new_session()
    try:
        return to_json(importer.preview_opening(s, data, _currency(s)))
    finally:
        s.close()


@bp.post("/import/opening/commit")
@require("import.run")
@doc("ورود موجودی اول دوره به‌صورت سند پیش‌نویس", response=ImportResult, idempotent=True)
def import_opening_commit() -> ResponseReturnValue:
    data = _upload()
    form = OpeningForm.model_validate(request.form.to_dict())
    actor = current_actor()
    if not actor.has("inventory.stock.create"):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("ثبت موجودی اول دوره نیازمند مجوز «ثبت رسید و حواله» است")
    with unit_of_work() as s:
        return idempotent(
            s,
            actor.user_id,
            lambda: importer.commit_opening(
                s, actor, data, _currency(s), form.warehouse_id, form.document_date
            ),
            status=201,
            body=data + form.model_dump_json().encode(),
        )
