"""HTTP client for the NEXTCAM server (standard library only; no browser involved)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from nextcam_agent import __version__


class ServerError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Unauthorized(ServerError):
    """The device token was revoked or replaced: stop and ask for pairing."""


class ServerClient:
    def __init__(self, server_url: str, token: str | None = None, timeout: float = 10.0) -> None:
        self.base = server_url.rstrip("/") + "/api/v1/devices/agent"
        self.token, self.timeout = token, timeout

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers["User-Agent"] = f"nextcam-agent/{__version__}"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(  # noqa: S310 - URL is the configured server
            self.base + path, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                data = resp.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read()).get("error", {})
            except (ValueError, AttributeError):
                err = {}
            cls = Unauthorized if e.code == 401 else ServerError
            raise cls(e.code, err.get("code", "error"), err.get("message", str(e.reason))) from e

    def pair(self, code: str, platform: str) -> dict[str, Any]:
        return self._post(
            "/pair", {"code": code, "agent_version": __version__, "platform": platform}
        )

    def poll(self, printer_state: str | None) -> dict[str, Any]:
        return self._post("/poll", {"agent_version": __version__, "printer_state": printer_state})

    def result(self, job_id: str, ok: bool, error: str | None = None) -> dict[str, Any]:
        return self._post(
            f"/jobs/{job_id}/result",
            {"status": "done" if ok else "failed", "error": error if not ok else None},
        )
