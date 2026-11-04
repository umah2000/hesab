"""Request timing (ADR-0031): the Server-Timing header only when switched on, the
slow-request log with the route, never for pages outside the API."""

from __future__ import annotations

import re

from flask import Flask
from structlog.testing import capture_logs

from app import create_app
from app.core.config import Settings
from tests.conftest import UNREACHABLE_URL


def _app(**kw: object) -> Flask:
    return create_app(
        Settings(env="test", database_url=UNREACHABLE_URL, secret_key="x", **kw)  # type: ignore[arg-type]
    )


def test_server_timing_is_off_by_default() -> None:
    r = _app().test_client().get("/api/v1/system/health")
    assert r.status_code == 200 and "Server-Timing" not in r.headers


def test_server_timing_and_slow_request_log() -> None:
    app = _app(server_timing=True, slow_request_ms=0)
    with capture_logs() as logs:
        r = app.test_client().get("/api/v1/system/health")
    assert re.fullmatch(
        r'app;dur=[\d.]+, db;dur=[\d.]+;desc="\d+ queries"', r.headers["Server-Timing"]
    )
    slow = [e for e in logs if e["event"] == "slow_request"]
    assert slow and slow[0]["route"] == "/api/v1/system/health" and slow[0]["status"] == 200
