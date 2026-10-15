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
        self.root = server_url.rstrip("/")
        self.base = self.root + "/api/v1/devices/agent"
        self.token, self.timeout = token, timeout

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", self.base + path, body)[1]

    def _call(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        extra: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, Any], str | None]:
        """(status, json body, ETag). 304 comes back as (304, {}, etag)."""
        headers = {"Accept": "application/json", "User-Agent": f"nextcam-agent/{__version__}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers.update(extra or {})
        req = urllib.request.Request(  # noqa: S310 - URL is the configured server
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:  # noqa: S310
                data = resp.read()
                return resp.status, (json.loads(data) if data else {}), resp.headers.get("ETag")
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return 304, {}, e.headers.get("ETag")
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

    def poll(self, printer_state: str | None, offline_queue: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"agent_version": __version__, "printer_state": printer_state}
        if offline_queue is not None:
            body["offline_queue"] = offline_queue
        return self._post("/poll", body)

    # --- offline sync (ADR-0017) ---------------------------------------------------------

    def snapshot(self, etag: str | None) -> tuple[dict[str, Any] | None, str | None]:
        """(snapshot, etag); (None, etag) when unchanged."""
        status, body, tag = self._call(
            "GET",
            self.root + "/api/v1/sync/agent/snapshot",
            extra={"If-None-Match": etag} if etag else None,
            timeout=max(self.timeout, 60.0),
        )
        return (None if status == 304 else body), tag

    def push(self, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _, body, _ = self._call(
            "POST", self.root + "/api/v1/sync/agent/push", {"ops": ops}, timeout=60.0
        )
        results: list[dict[str, Any]] = body["results"]
        return results

    def result(self, job_id: str, ok: bool, error: str | None = None) -> dict[str, Any]:
        return self._post(
            f"/jobs/{job_id}/result",
            {"status": "done" if ok else "failed", "error": error if not ok else None},
        )
