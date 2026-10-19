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
    proxy: dict[str, object] = {}
    if settings.trusted_proxy:
        proxy = {
            "trusted_proxy": settings.trusted_proxy,
            "trusted_proxy_count": 1,
            "trusted_proxy_headers": {"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"},
            "clear_untrusted_proxy_headers": True,
        }
    serve(
        app,
        host=settings.host,
        port=settings.port,
        threads=settings.threads,
        ident="nextcam",
        **proxy,
    )


if __name__ == "__main__":
    main()
