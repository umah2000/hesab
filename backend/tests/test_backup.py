"""Backup, verification, restore test and the offsite-copy warning (risk R2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import Result
from flask import Flask
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.modules.system.backup_crypto import decrypt_file, generate_key, parse_key, sha256_file
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


@pytest.mark.skipif(
    not os.environ.get("TEST_BACKUP_READ_DIR"),
    reason="needs SQL Server's backup folder readable here (TEST_BACKUP_READ_DIR)",
)
def test_encrypted_copy_and_restore_from_copy(app: Flask, seed: Seed, tmp_path: Path) -> None:
    settings = app.config["SETTINGS"]
    read_dir = Path(os.environ["TEST_BACKUP_READ_DIR"])
    usb = tmp_path / "usb"
    settings.backup_dir = "/var/opt/mssql/backup"
    settings.backup_read_dir = str(read_dir)
    settings.backup_key = SecretStr(generate_key())
    settings.backup_copy_dir = str(usb)
    try:
        out = run(app, "backup")
        assert out.exit_code == 0, out.output
        assert "encrypted copy ok" in out.output and "decrypted and compared" in out.output
        copies = list(usb.glob("nextcam_*.bak.ncbk"))
        assert len(copies) == 1
        bak = read_dir / copies[0].name.removesuffix(".ncbk")
        # The copy holds the backup, encrypted: same plaintext digest, no plaintext inside.
        key = parse_key(settings.backup_key.get_secret_value())
        assert decrypt_file(copies[0], None, key) == sha256_file(bak)
        assert copies[0].read_bytes()[:4] == b"NCBK"

        # The periodic restore test restores the encrypted copy (what a recovery would use)
        # and leaves no decrypted file behind.
        rt = run(app, "backup-restore-test")
        assert rt.exit_code == 0, rt.output
        assert ".ncbk" in rt.output and "'organizations': 1" in rt.output
        assert not list(read_dir.glob("nextcam_restoretest_*"))

        # A damaged copy or a different key fails loudly and is recorded.
        damaged = tmp_path / "damaged.bak.ncbk"
        blob = bytearray(copies[0].read_bytes())
        blob[len(blob) // 2] ^= 0xFF
        damaged.write_bytes(bytes(blob))
        bad = run(app, "backup-restore-test", "--file", str(damaged))
        assert bad.exit_code != 0
        settings.backup_key = SecretStr(generate_key())
        assert run(app, "backup-restore-test").exit_code != 0
    finally:
        settings.backup_dir = settings.backup_read_dir = None
        settings.backup_key = settings.backup_copy_dir = None
        for f in read_dir.glob("nextcam_restoretest_*"):
            f.unlink()

    make_user(app, "boss2", ["MGR"])
    boss = Api(app.test_client())
    assert boss.login("boss2").status_code == 200
    st = boss.get("/api/v1/system/backups").get_json()
    # The verified copy counts as the offsite copy: no offsite warning.
    assert not any("بیرون" in w for w in st["warnings"])
    kinds = [(h["kind"], h["status"]) for h in st["history"]]
    assert kinds[:5] == [
        ("restore_test", "failed"),
        ("restore_test", "failed"),
        ("restore_test", "ok"),
        ("copy", "ok"),
        ("backup", "ok"),
    ]
    damaged_msg = st["history"][1]["message"]
    assert "آسیب" in damaged_msg or "ناقص" in damaged_msg


def test_copies_are_never_plaintext() -> None:
    with pytest.raises(ValidationError, match="backup_key"):
        Settings(
            database_url="mssql+pyodbc://x",  # type: ignore[arg-type]
            secret_key="x",  # type: ignore[arg-type]
            backup_copy_dir="/media/usb",
        )
    with pytest.raises(ValidationError, match="32 bytes"):
        Settings(
            database_url="mssql+pyodbc://x",  # type: ignore[arg-type]
            secret_key="x",  # type: ignore[arg-type]
            backup_key="short",  # type: ignore[arg-type]
        )
