"""Backup, verification, restore test and the offsite-copy warning (risk R2)."""

from __future__ import annotations

import pytest
from click.testing import Result
from flask import Flask

from tests.conftest import Api, Seed, make_user

pytestmark = pytest.mark.db


def run(app: Flask, *args: str) -> Result:
    return app.test_cli_runner().invoke(args=list(args))


def test_backup_restore_test_and_warnings(app: Flask, seed: Seed) -> None:
    make_user(app, "boss", ["MGR"])
    boss = Api(app.test_client())
    assert boss.login("boss").status_code == 200
    st = boss.get("/api/v1/system/backups").get_json()
    assert st["last_backup"] is None and len(st["warnings"]) == 3

    app.config["SETTINGS"].backup_dir = "/var/opt/mssql/backup"
    try:
        out = run(app, "backup")
        assert out.exit_code == 0, out.output
        assert "verified" in out.output
        rt = run(app, "backup-restore-test")
        assert rt.exit_code == 0, rt.output
        assert "'organizations': 1" in rt.output
        bad = run(app, "backup-restore-test", "--file", "/var/opt/mssql/backup/missing.bak")
        assert bad.exit_code != 0
    finally:
        app.config["SETTINGS"].backup_dir = None

    st = boss.get("/api/v1/system/backups").get_json()
    assert st["last_backup"]["verified"] is True and st["last_restore_test"]["status"] == "ok"
    # The newest restore-test attempt failed, but a good one exists; still nags about offsite.
    assert any("بیرون" in w for w in st["warnings"])
    assert boss.post("/api/v1/system/backups/offsite-copied").status_code == 200
    st = boss.get("/api/v1/system/backups").get_json()
    assert st["warnings"] == []
    kinds = [(h["kind"], h["status"]) for h in st["history"]]
    assert kinds[:3] == [("restore_test", "failed"), ("restore_test", "ok"), ("backup", "ok")]
    assert boss.post("/api/v1/system/backups/run").status_code == 403  # settings.manage only
