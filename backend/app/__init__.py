"""NEXTCAM ERP backend — Flask application factory."""

from __future__ import annotations

from flask import Flask

from app.core.config import Settings, get_settings
from app.core.db import init_db
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.env != "development")

    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    app.config["SECRET_KEY"] = settings.secret_key.get_secret_value()

    init_db(app, settings)
    register_error_handlers(app)

    from app.modules.system.api import bp as system_bp

    app.register_blueprint(system_bp, url_prefix="/api/v1/system")
    return app
