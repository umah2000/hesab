"""Agent settings and the device token on disk.

Everything lives in one data directory (Windows: ``%ProgramData%\\NEXTCAM\\agent``):
``agent.json`` (server URL, device id) and ``token.bin``. On Windows the token is
encrypted with DPAPI for the machine, so copying the file to another PC is useless;
elsewhere it is a file readable only by the service account (mode 0600).
The token is never logged.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("NEXTCAM_AGENT_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "NEXTCAM" / "agent"
    return Path.home() / ".nextcam-agent"


@dataclass
class AgentConfig:
    server_url: str
    device_id: str
    device_name: str
    poll_interval: float = 1.0
    # Local diagnostics page; bound to 127.0.0.1 only.
    status_port: int = 47615
    # Development only: send print jobs here instead of the configured printer
    # (e.g. "file:C:\\temp\\receipts.bin"); never set on a register.
    printer_override: str | None = None


def load() -> AgentConfig | None:
    path = data_dir() / "agent.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return AgentConfig(**raw)


def save(cfg: AgentConfig) -> None:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent.json").write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), "utf-8")


# --- token -------------------------------------------------------------------------


def _dpapi(data: bytes, protect: bool) -> bytes:
    """CryptProtectData / CryptUnprotectData with the local-machine scope (Windows)."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = Blob(len(data), buf), Blob()
    local_machine = 0x4  # CRYPTPROTECT_LOCAL_MACHINE: the service account can read it
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, None, None, None, local_machine, ctypes.byref(dst))
    if not ok:
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        kernel32.LocalFree(dst.pbData)


def save_token(token: str) -> None:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / "token.bin"
    raw = token.encode()
    if sys.platform == "win32":
        raw = _dpapi(raw, protect=True)
    path.write_bytes(raw)
    if sys.platform != "win32":
        path.chmod(0o600)


def load_token() -> str | None:
    path = data_dir() / "token.bin"
    if not path.exists():
        return None
    raw = path.read_bytes()
    if sys.platform == "win32":
        raw = _dpapi(raw, protect=False)
    return raw.decode()


def forget() -> None:
    for name in ("token.bin", "agent.json"):
        p = data_dir() / name
        if p.exists():
            p.unlink()
