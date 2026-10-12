from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from tests.conftest import _wipe

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.db
def test_upgrade_and_downgrade_roundtrip(db_url: str) -> None:
    # Downgrades refuse to drop history (e.g. sales stock documents), so start empty.
    _wipe(db_url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = db_url
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.mark.db
def test_models_match_migrations(db_url: str) -> None:
    """Fails when a model changed without a migration."""
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = db_url
    command.upgrade(cfg, "head")
    command.check(cfg)
