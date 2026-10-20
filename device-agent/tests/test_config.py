"""Token and settings storage. On the Windows CI runner this exercises DPAPI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nextcam_agent import config


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NEXTCAM_AGENT_HOME", str(tmp_path))
    return tmp_path


def test_token_round_trip_is_not_plain_on_windows(home: Path) -> None:
    config.save_token("secret-device-token")
    raw = (home / "token.bin").read_bytes()
    assert config.load_token() == "secret-device-token"
    if sys.platform == "win32":
        assert b"secret-device-token" not in raw  # DPAPI-encrypted
    else:
        assert (home / "token.bin").stat().st_mode & 0o777 == 0o600


def test_settings_round_trip_and_forget(home: Path) -> None:
    cfg = config.AgentConfig("http://192.168.1.10:8080", "d1", "صندوق ۱")
    config.save(cfg)
    assert config.load() == cfg
    config.save_token("t")
    config.forget()
    assert config.load() is None and config.load_token() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows service wrapper")
def test_windows_service_module_imports() -> None:
    from nextcam_agent import service

    assert service.AgentService._svc_name_ == "NextcamAgent"
