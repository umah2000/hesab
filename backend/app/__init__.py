"""NEXTCAM ERP backend — Flask application factory."""

from __future__ import annotations

from flask import Flask

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
    from app.modules.iam.api import auth_bp, roles_bp, users_bp
    from app.modules.inventory.api import bp as inventory_bp
    from app.modules.organization.api import bp as org_bp
    from app.modules.system.api import bp as system_bp

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
    register_cli(app)
    return app
