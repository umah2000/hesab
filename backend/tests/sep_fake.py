"""A stand-in for Saman's central PC-POS service, shaped only as its document v1.4 shows.

It is a test double for the program's side of the conversation: it proves the requests
the driver sends and how it reads the documented answers. It says nothing about how the
real service behaves beyond the document (open-questions Q1): that needs Saman's test
service.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CLIENT = ("ro.client", "client-secret-for-tests")
USER = ("pos-user", "user-password-for-tests")


def ok(data: dict[str, Any] | None) -> dict[str, Any]:
    return {"IsSuccess": True, "ErrorCode": 0, "ErrorDescription": None, "Data": data}


def fail(code: int, text: str = "") -> dict[str, Any]:
    return {"IsSuccess": False, "ErrorCode": code, "ErrorDescription": text, "Data": None}


@dataclass
class Call:
    path: str
    headers: dict[str, str]
    body: Any


@dataclass
class FakeSep:
    """``pay``/``inquiry`` decide the answers; every request is kept in ``calls``."""

    pay: Callable[[dict[str, Any]], tuple[int, dict[str, Any]]] | None = None
    inquiry: Callable[[dict[str, Any]], tuple[int, dict[str, Any]]] | None = None
    pay_delay: float = 0.0
    ident_delay: float = 0.0
    expire_next_token: bool = False
    calls: list[Call] = field(default_factory=list)
    tokens_issued: int = 0
    _ids: int = 0

    def __post_init__(self) -> None:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                status, answer = fake.handle(self.path, dict(self.headers), raw)
                out = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def ops(self) -> list[str]:
        return [c.path.rsplit("/", 1)[-1] for c in self.calls]

    def handle(self, path: str, headers: dict[str, str], raw: bytes) -> tuple[int, Any]:
        if path == "/ids/connect/token":
            form = dict(urllib.parse.parse_qsl(raw.decode()))
            self.calls.append(Call(path, headers, form))
            basic = base64.b64encode(f"{CLIENT[0]}:{CLIENT[1]}".encode()).decode()
            if (
                headers.get("Authorization") != f"Basic {basic}"
                or form.get("grant_type") != "password"
                or (form.get("username"), form.get("password")) != USER
            ):
                return 400, {"error": "invalid_grant"}
            self.tokens_issued += 1
            token = f"token-{self.tokens_issued}"
            return 200, {
                "access_token": token,
                "expires_in": 3600,
                "token_type": "Bearer",
                "refresh_token": "r",
            }
        body = json.loads(raw or b"{}")
        self.calls.append(Call(path, headers, body))
        if headers.get("Authorization") != f"Bearer token-{self.tokens_issued}":
            return 401, {"Message": "Authorization has been denied for this request."}
        if self.expire_next_token:
            self.expire_next_token = False
            return 401, {"Message": "Authorization has been denied for this request."}
        op = path.rsplit("/", 1)[-1]
        if op == "ReciveIdentifier":
            if self.ident_delay:
                time.sleep(self.ident_delay)
            self._ids += 1
            return 200, ok({"Identifier": f"4f1653f7-f971-4d59-ae2c-{self._ids:012d}"})
        if op == "StartPayment":
            if self.pay_delay:
                time.sleep(self.pay_delay)
            return self.pay(body) if self.pay else (200, approved(body))
        if op == "Inquery":
            return self.inquiry(body) if self.inquiry else (200, fail(8, "not found"))
        return 404, {"Message": "No HTTP resource was found"}


def approved(body: dict[str, Any], amount: str | None = None) -> dict[str, Any]:
    """The success answer of StartPayment/Inquery as in the document's screenshots."""
    return ok(
        {
            "Identifier": body.get("Identifier"),
            "TerminalID": body.get("TerminalID"),
            "CreateOn": "2019-07-17T16:12:01.5283125+04:30",
            "ResponseCode": "00",
            "ResponseDescription": "عملیات موفق",
            "TraceNumber": "500540",
            "ResNum": body.get("ResNum"),
            "RRN": "802151113805",
            "State": 0,
            "StateDescription": "transaction done",
            "Amount": amount if amount is not None else body.get("Amount", "110000"),
        }
    )
