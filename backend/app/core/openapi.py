"""Minimal OpenAPI 3.1 generation from Pydantic models attached with ``@doc``."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, TypeVar

from flask import Blueprint, Flask, current_app, jsonify
from flask.typing import ResponseReturnValue
from pydantic import BaseModel

F = TypeVar("F", bound=Callable[..., Any])


def doc(
    summary: str,
    *,
    body: type[BaseModel] | None = None,
    response: Any = None,
    query: type[BaseModel] | None = None,
    idempotent: bool = False,
    versioned: bool = False,
) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        fn.__openapi__ = {  # type: ignore[attr-defined]
            "summary": summary,
            "body": body,
            "response": response,
            "query": query,
            "idempotent": idempotent,
            "versioned": versioned,
        }
        return fn

    return decorator


def _schema(model: Any, components: dict[str, Any]) -> dict[str, Any]:
    if model is None:
        return {}
    if isinstance(model, list):
        return {"type": "array", "items": _schema(model[0], components)}
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    for name, sub in schema.pop("$defs", {}).items():
        components[name] = sub
    name = model.__name__
    components[name] = schema
    return {"$ref": f"#/components/schemas/{name}"}


def build_spec(app: Flask) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    components: dict[str, Any] = {}
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        view = app.view_functions[rule.endpoint]
        meta = getattr(view, "__openapi__", None)
        if meta is None:
            continue
        path = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", rule.rule)
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            op: dict[str, Any] = {"summary": meta["summary"], "tags": [rule.endpoint.split(".")[0]]}
            perm = getattr(view, "required_permission", None)
            if perm:
                op["x-required-permission"] = perm
            params = [
                {"name": a, "in": "path", "required": True, "schema": {"type": "string"}}
                for a in rule.arguments
            ]
            if meta["query"] is not None:
                props = meta["query"].model_json_schema().get("properties", {})
                params += [{"name": k, "in": "query", "schema": v} for k, v in props.items()]
            if meta["idempotent"]:
                params.append(
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "format": "uuid"},
                    }
                )
            if meta["versioned"]:
                params.append(
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                )
            if params:
                op["parameters"] = params
            if meta["body"] is not None:
                op["requestBody"] = {
                    "required": True,
                    "content": {"application/json": {"schema": _schema(meta["body"], components)}},
                }
            resp_schema = _schema(meta["response"], components)
            op["responses"] = {
                "200": {
                    "description": "OK",
                    **(
                        {"content": {"application/json": {"schema": resp_schema}}}
                        if resp_schema
                        else {}
                    ),
                },
                "default": {
                    "description": "Error",
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
                    },
                },
            }
            paths.setdefault(path, {})[method.lower()] = op
    components["Error"] = {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {},
                    "incident": {"type": "string"},
                },
            }
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "NEXTCAM ERP API", "version": "v1"},
        "paths": paths,
        "components": {"schemas": components},
    }


bp = Blueprint("openapi", __name__)


@bp.get("/openapi.json")
def openapi_json() -> ResponseReturnValue:
    return jsonify(build_spec(current_app))
