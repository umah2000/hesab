"""Safe upgrade (docs/install/upgrade.md): activity guard, backup first, all-or-nothing."""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from flask import Flask
from sqlalchemy import text

from app.core.db import new_session, utcnow
from app.modules.system import upgrade
from tests.conftest import Api, Seed
from tests.test_inventory import Inv, inv, keeper, make_item, stock_doc  # noqa: F401 - fixtures

pytestmark = pytest.mark.db

BROKEN = '''"""broken on purpose"""

import sqlalchemy as sa
from alembic import op

revision = "9999"
down_revision = "{head}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("upgrade_probe", sa.Column("id", sa.Integer, primary_key=True))
    op.execute("SELECT 1/0")


def downgrade() -> None:
    op.drop_table("upgrade_probe")
'''


def _sql(app: Flask, sql: str) -> object:
    with app.app_context():
        s = new_session()
        try:
            return s.scalar(text(sql))
        finally:
            s.close()


def test_upgrade_guards_backs_up_and_checks(app: Flask, seed: Seed, keeper: Api) -> None:  # noqa: F811
    engine = app.extensions["db_engine"]
    cfg = upgrade.alembic_config(engine)
    _, head = upgrade.revisions(engine)
    command.downgrade(cfg, "0013")  # an installation one release behind
    assert upgrade.revisions(engine)[0] == "0013"

    # The keeper's session was just used: refuse.
    with pytest.raises(upgrade.UpgradeError, match="در حال استفاده"):
        upgrade.run(app, echo=lambda _: None)
    assert upgrade.revisions(engine)[0] == "0013"
    with app.app_context():
        s = new_session()
        try:
            s.execute(
                text("UPDATE user_session SET last_seen_at = :t"),
                {"t": utcnow() - timedelta(minutes=10)},
            )
            s.commit()
        finally:
            s.close()

    settings = app.config["SETTINGS"]
    settings.backup_dir = "/var/opt/mssql/backup"
    lines: list[str] = []
    try:
        report = upgrade.run(app, echo=lines.append)
    finally:
        settings.backup_dir = None
    assert report.migrated and report.from_revision == "0013" and report.to_revision == head
    assert report.backup and report.backup.endswith(".bak")
    assert report.ok, report.checks
    assert {c.name for c in report.checks} == {
        "schema",
        "organization",
        "vouchers balanced",
        "stock = ledger",
    }
    assert any("backup ok" in ln for ln in lines)
    assert _sql(app, "SELECT COUNT(*) FROM audit_event WHERE action = 'system.upgraded'") == 1
    # Running it again is a no-op apart from the checks.
    again = upgrade.run(app, echo=lambda _: None)
    assert not again.migrated and again.ok


def test_failed_migration_rolls_everything_back(
    app: Flask, seed: Seed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = app.extensions["db_engine"]
    _, head = upgrade.revisions(engine)
    command.downgrade(upgrade.alembic_config(engine), "0013")
    scripts = tmp_path / "migrations"
    shutil.copytree(upgrade.MIGRATIONS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (scripts / "versions" / "29991231_9999_broken.py").write_text(
        BROKEN.replace("{head}", str(head)), "utf-8"
    )
    monkeypatch.setattr(upgrade, "MIGRATIONS", scripts)
    try:
        with pytest.raises(upgrade.UpgradeError, match="کامل برگشت داده شد"):
            upgrade.run(app, skip_backup=True, force=True, echo=lambda _: None)
        # 0014 and 0015 ran before the broken one, yet nothing of them remains.
        assert upgrade.revisions(engine)[0] == "0013"
        assert _sql(app, "SELECT OBJECT_ID('license')") is None
        assert _sql(app, "SELECT OBJECT_ID('upgrade_probe')") is None
        # The old release still works on this database.
        assert _sql(app, "SELECT COUNT(*) FROM organization") == 1
    finally:
        monkeypatch.undo()
        command.upgrade(upgrade.alembic_config(engine), "head")
    assert upgrade.revisions(engine)[0] == head


def test_integrity_check_finds_stock_drift(app: Flask, inv: Inv, keeper: Api) -> None:  # noqa: F811
    item = make_item(keeper, inv, "DRIFT1")
    stock_doc(keeper, "opening", inv.wh_a, [{"item_id": item["id"], "qty": "10", "unit_cost": "5"}])
    engine = app.extensions["db_engine"]
    assert all(c.ok for c in upgrade.integrity_checks(engine))
    with app.app_context():
        s = new_session()
        try:
            s.execute(text("UPDATE stock_balance SET qty = qty + 1"))
            s.commit()
        finally:
            s.close()
    bad = {c.name: c for c in upgrade.integrity_checks(engine)}
    assert not bad["stock = ledger"].ok and bad["stock = ledger"].detail.startswith("1 ")
    out = app.test_cli_runner().invoke(args=["check-integrity"])
    assert out.exit_code == 2 and "[FAIL] stock = ledger" in out.output


def test_first_install_on_an_empty_database(db_url: str, migrated_db: str | None) -> None:
    from app import create_app
    from tests.conftest import _settings, _wipe

    _wipe(db_url)
    app = create_app(_settings(db_url))
    engine = app.extensions["db_engine"]
    command.downgrade(upgrade.alembic_config(engine), "base")
    assert upgrade.revisions(engine)[0] is None
    report = upgrade.run(app, skip_backup=True, echo=lambda _: None)
    assert report.migrated and report.to_revision == upgrade.revisions(engine)[1]
    assert report.ok, report.checks
    org = next(c for c in report.checks if c.name == "organization")
    assert "flask setup" in org.detail
