"""Request parsing and response helpers shared by all modules."""

from __future__ import annotations

import uuid
from typing import Any, TypeVar

from flask import Response, jsonify, request
from pydantic import BaseModel, Field

from app.core.errors import DomainError

M = TypeVar("M", bound=BaseModel)

MAX_PAGE_SIZE = 200


def parse_body(model: type[M]) -> M:
    data = request.get_json(silent=True)
    if data is None:
        raise DomainError("بدنه درخواست باید JSON معتبر باشد", code="invalid_json")
    return model.model_validate(data)


def parse_query(model: type[M]) -> M:
    return model.model_validate(request.args.to_dict())


def to_json(payload: BaseModel | list[BaseModel] | dict[str, Any], status: int = 200) -> Response:
    if isinstance(payload, BaseModel):
        body: Any = payload.model_dump(mode="json")
    elif isinstance(payload, list):
        body = [p.model_dump(mode="json") for p in payload]
    else:
        body = payload
    resp = jsonify(body)
    resp.status_code = status
    return resp


def if_match() -> str:
    """Row version the client last saw (ADR-0006). Required for updates."""
    value = (request.headers.get("If-Match") or "").strip().strip('"')
    if not value:
        raise DomainError("هدر If-Match الزامی است", code="if_match_required")
    return value


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise DomainError("شناسه نامعتبر است", code="invalid_id") from e


class PageQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)
    q: str | None = Field(default=None, max_length=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
