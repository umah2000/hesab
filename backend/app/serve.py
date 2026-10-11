"""Production entry point: ``python -m app.serve`` (waitress, Windows-friendly).

Settings come from the environment / .env (NEXTCAM_*). See docs/install/lan-install.md.
"""

from __future__ import annotations

from waitress import serve

from app import create_app
from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    app = create_app(settings)
    serve(app, host=settings.host, port=settings.port, threads=settings.threads, ident="nextcam")


if __name__ == "__main__":
    main()
