"""System endpoints: liveness and readiness (database reachability)."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify
from flask.typing import ResponseReturnValue
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

bp = Blueprint("system", __name__)


@bp.get("/health")
def health() -> ResponseReturnValue:
    return jsonify({"status": "ok"})


@bp.get("/ready")
def ready() -> ResponseReturnValue:
    try:
        with current_app.extensions["db_engine"].connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        current_app.logger.warning("database not reachable")
        return jsonify({"status": "unavailable", "database": "down"}), 503
    return jsonify({"status": "ok", "database": "up"})
