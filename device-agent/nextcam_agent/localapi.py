"""Read-only diagnostics on http://127.0.0.1:<port>/status for the technician.

It has no commands at all: printing and the drawer only ever come from the server
queue (ADR-0015). Defences anyway, because any web page can try to reach localhost:
bound to 127.0.0.1 only; the Host header must name 127.0.0.1/localhost (DNS
rebinding); any request carrying an Origin header (i.e. sent by a web page) is refused;
no CORS headers are ever sent.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from nextcam_agent import __version__


def make_server(port: int, snapshot: Callable[[], dict[str, Any]]) -> ThreadingHTTPServer:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "nextcam-agent"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _send(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _guard(self) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                self._send(403, {"error": "host"})
                return False
            if self.headers.get("Origin") is not None:
                self._send(403, {"error": "origin"})
                return False
            return True

        def do_GET(self) -> None:
            if not self._guard():
                return
            if self.path == "/status":
                self._send(200, {"version": __version__, **snapshot()})
            else:
                self._send(404, {"error": "not_found"})

        def _refuse(self) -> None:
            self._send(405, {"error": "read_only"})

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve_in_background(port: int, snapshot: Callable[[], dict[str, Any]]) -> ThreadingHTTPServer:
    srv = make_server(port, snapshot)
    threading.Thread(target=srv.serve_forever, name="status-api", daemon=True).start()
    return srv
