"""Per-request timing (ADR-0031): wall time, time in SQL Server and number of statements.

- A request slower than ``NEXTCAM_SLOW_REQUEST_MS`` (500) is logged as ``slow_request``
  with its route, so the slowest paths of a real shop can be found without a profiler.
- With ``NEXTCAM_SERVER_TIMING=true`` every API answer carries a ``Server-Timing``
  header (``app``, ``db`` and the statement count), which browsers show in DevTools.
  Off by default: it tells an outsider how the server spends its time.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from flask import Flask, Response, g, has_request_context, request
from sqlalchemy import event
from sqlalchemy.engine import Engine

log = structlog.get_logger("perf")


def instrument(app: Flask, engine: Engine, slow_ms: int, header: bool) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def _start(
        conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool
    ) -> None:
        if has_request_context():
            g._perf_q = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _end(conn: Any, cursor: Any, statement: str, params: Any, context: Any, many: bool) -> None:
        if has_request_context() and "_perf_q" in g:
            g._perf_db = g.get("_perf_db", 0.0) + time.perf_counter() - g._perf_q
            g._perf_n = g.get("_perf_n", 0) + 1

    @app.before_request
    def _begin() -> None:
        g._perf_t0 = time.perf_counter()

    @app.after_request
    def _report(resp: Response) -> Response:
        t0 = g.get("_perf_t0")
        if t0 is None or not request.path.startswith("/api/"):
            return resp
        total = (time.perf_counter() - t0) * 1000
        db = g.get("_perf_db", 0.0) * 1000
        n = g.get("_perf_n", 0)
        if header:
            resp.headers["Server-Timing"] = (
                f'app;dur={total - db:.1f}, db;dur={db:.1f};desc="{n} queries"'
            )
        if total >= slow_ms:
            log.warning(
                "slow_request",
                method=request.method,
                route=request.url_rule.rule if request.url_rule else request.path,
                status=resp.status_code,
                ms=round(total, 1),
                db_ms=round(db, 1),
                queries=n,
            )
        return resp
