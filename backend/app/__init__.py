"""NEXTCAM ERP backend — Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, abort, send_from_directory
from flask.typing import ResponseReturnValue

from app.core.config import Settings, get_settings
from app.core.db import init_db
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.ratelimit import limiter


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.env != "development")

    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    app.config["SECRET_KEY"] = settings.secret_key.get_secret_value()
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    app.json.ensure_ascii = False  # type: ignore[attr-defined]

    init_db(app, settings)
    limiter.init_app(app)
    register_error_handlers(app)

    # Importing models registers every table on Base.metadata (Alembic relies on this).
    from app import models  # noqa: F401
    from app.cli import register_cli
    from app.core.openapi import bp as openapi_bp
    from app.modules.accounting.api import bp as accounting_bp
    from app.modules.audit.api import bp as audit_bp
    from app.modules.devices.api import bp as devices_bp
    from app.modules.distribution.api import bp as distribution_bp
    from app.modules.iam.api import auth_bp, roles_bp, users_bp
    from app.modules.inventory.api import bp as inventory_bp
    from app.modules.organization.api import bp as org_bp
    from app.modules.parties.api import bp as parties_bp
    from app.modules.purchasing.api import bp as purchasing_bp
    from app.modules.reports.api import bp as reports_bp
    from app.modules.sales.api import bp as sales_bp
    from app.modules.sales.api import payments_bp
    from app.modules.sync.api import bp as sync_bp
    from app.modules.system.api import bp as system_bp
    from app.modules.treasury.api import bp as treasury_bp

    api = "/api/v1"
    app.register_blueprint(system_bp, url_prefix=f"{api}/system")
    app.register_blueprint(openapi_bp, url_prefix=api)
    app.register_blueprint(auth_bp, url_prefix=f"{api}/auth")
    app.register_blueprint(users_bp, url_prefix=f"{api}/users")
    app.register_blueprint(roles_bp, url_prefix=f"{api}/roles")
    app.register_blueprint(org_bp, url_prefix=f"{api}/organization")
    app.register_blueprint(audit_bp, url_prefix=f"{api}/audit")
    app.register_blueprint(accounting_bp, url_prefix=f"{api}/accounting")
    app.register_blueprint(inventory_bp, url_prefix=f"{api}/inventory")
    app.register_blueprint(sales_bp, url_prefix=f"{api}/sales")
    app.register_blueprint(parties_bp, url_prefix=f"{api}/parties")
    app.register_blueprint(purchasing_bp, url_prefix=f"{api}/purchasing")
    app.register_blueprint(treasury_bp, url_prefix=f"{api}/treasury")
    app.register_blueprint(devices_bp, url_prefix=f"{api}/devices")
    app.register_blueprint(reports_bp, url_prefix=f"{api}/reports")
    app.register_blueprint(payments_bp, url_prefix=f"{api}/payments")
    app.register_blueprint(sync_bp, url_prefix=f"{api}/sync")
    app.register_blueprint(distribution_bp, url_prefix=f"{api}/distribution")
    register_cli(app)
    if settings.static_dir:
        _serve_frontend(app, Path(settings.static_dir))

    @app.after_request
    def _security_headers(resp: Response) -> Response:
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    return app


def _serve_frontend(app: Flask, root: Path) -> None:
    """Serve the built single-page app; every non-API path falls back to index.html."""
    root = root.resolve()
    if not (root / "index.html").is_file():
        raise RuntimeError(f"NEXTCAM_STATIC_DIR has no index.html: {root}")

    def spa(path: str = "") -> ResponseReturnValue:
        if path.startswith("api/"):
            abort(404)
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            resp = send_from_directory(root, path)
            if path.startswith("assets/"):  # content-hashed file names
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp
        resp = send_from_directory(root, "index.html")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    app.add_url_rule("/", "spa_index", spa)
    app.add_url_rule("/<path:path>", "spa", spa)
