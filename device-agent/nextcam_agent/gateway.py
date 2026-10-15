"""The register gateway on http://127.0.0.1:47616 (ADR-0017).

The register's browser opens the POS here instead of on the server:

* **Online** every request is passed to the server unchanged (cookies, CSRF, ETags).
  The pages it fetches are kept on disk, so the POS still loads after a reload while
  the server is unreachable (localhost is a secure context; a LAN page is not, which is
  why the browser never talks to the agent any other way, ADR-0015).
* **Offline** the POS endpoints are answered here, in the server's shapes, from the
  snapshot and with the shared pricing core; every other endpoint answers 503 so the
  page says what is unavailable. Responses carry ``X-Nextcam-Mode: online|offline`` and
  ``X-Nextcam-Queue: <pending sales>``.

Offline, only a browser whose session the server accepted while online, and whose user
holds the register's open shift, may sell. Defences, since any web page can try to
reach localhost: bound to 127.0.0.1; Host must be 127.0.0.1/localhost (DNS rebinding);
state-changing requests from another origin are refused; the CSRF double-submit cookie
is checked offline exactly as the server checks it online; no CORS headers, ever.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import mimetypes
import re
import ssl
import threading
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from nextcam_agent import offline
from nextcam_agent.offline import OfflineError, Snapshot
from nextcam_agent.syncer import Local

log = logging.getLogger("nextcam_agent.gateway")

SESSION_COOKIE = "nextcam_session"
CSRF_COOKIE = "nextcam_csrf"
FORWARD_REQUEST = {
    "accept",
    "accept-language",
    "content-type",
    "cookie",
    "idempotency-key",
    "if-match",
    "if-none-match",
    "x-csrf-token",
}
FORWARD_RESPONSE = {
    "cache-control",
    "content-disposition",
    "content-type",
    "etag",
    "last-modified",
    "set-cookie",
}
STATIC_TYPES = ("text/html", "javascript", "text/css", "font/", "image/", "manifest+json")
OFFLINE_MESSAGE = "سرور در دسترس نیست؛ این بخش در حالت آفلاین کار نمی‌کند"

PrintFn = Callable[[dict[str, Any], dict[str, Any]], tuple[bool, str | None]]


@dataclass
class Reply:
    status: int
    body: bytes = b""
    headers: list[tuple[str, str]] = field(default_factory=list)


def _json(status: int, payload: Any, *extra: tuple[str, str]) -> Reply:
    data = json.dumps(payload, ensure_ascii=False).encode()
    return Reply(status, data, [("Content-Type", "application/json"), *extra])


def _error(status: int, code: str, message: str) -> Reply:
    return _json(status, {"error": {"code": code, "message": message}})


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Unreachable(Exception):
    """The server did not answer (connection refused, reset, timeout)."""


class Gateway:
    def __init__(
        self,
        server_url: str,
        local: Local,
        cache_dir: Path,
        *,
        port: int = 47616,
        device_id: str | None = None,
        print_fn: PrintFn | None = None,
        api_timeout: float = 10.0,
        page_timeout: float = 30.0,
    ) -> None:
        self.server = urllib.parse.urlsplit(server_url.rstrip("/"))
        self.local, self.port, self.device_id = local, port, device_id
        self.cache = cache_dir
        self.print_fn = print_fn
        self.api_timeout, self.page_timeout = api_timeout, page_timeout
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{h}" for h in self.hosts}
        self.jobs: dict[str, dict[str, Any]] = {}
        self._print_lock = threading.Lock()

    # --- entry point ---------------------------------------------------------------------

    def handle(self, method: str, target: str, headers: dict[str, str], body: bytes) -> Reply:
        h = {k.lower(): v for k, v in headers.items()}
        if h.get("host", "") not in self.hosts:
            return _error(403, "host", "Host نامعتبر است")
        if method not in ("GET", "HEAD"):
            origin = h.get("origin")
            site = h.get("sec-fetch-site")
            if (origin is not None and origin not in self.origins) or (
                site is not None and site not in ("same-origin", "none")
            ):
                return _error(403, "origin", "درخواست از مبدأ دیگر پذیرفته نمی‌شود")
        path = urllib.parse.urlsplit(target).path
        if path.startswith("/local/"):
            return self._local(method, path)
        if path.startswith("/api/"):
            return self._api(method, target, h, body)
        if method != "GET":
            return _error(405, "method", "روش مجاز نیست")
        return self._page(target, h)

    def _stamp(self, r: Reply, mode: str) -> Reply:
        r.headers += [
            ("X-Nextcam-Mode", mode),
            ("X-Nextcam-Queue", str(self.local.store.pending_count())),
            ("Cache-Control", "no-store"),
        ]
        return r

    # --- forwarding ----------------------------------------------------------------------

    def _forward(
        self, method: str, target: str, h: dict[str, str], body: bytes, timeout: float
    ) -> Reply:
        s = self.server
        conn: http.client.HTTPConnection
        if s.scheme == "https":
            conn = http.client.HTTPSConnection(
                s.hostname or "", s.port, timeout=timeout, context=ssl.create_default_context()
            )
        else:
            conn = http.client.HTTPConnection(s.hostname or "", s.port, timeout=timeout)
        fwd = {k: v for k, v in h.items() if k in FORWARD_REQUEST}
        try:
            conn.request(method, s.path + target, body=body or None, headers=fwd)
            resp = conn.getresponse()
            data = resp.read()
            out = []
            for k, v in resp.getheaders():
                lk = k.lower()
                if lk not in FORWARD_RESPONSE:
                    continue
                if lk == "set-cookie":
                    # Browser ↔ gateway is loopback http; the server hop keeps its TLS.
                    v = re.sub(r";\s*Secure(?=;|$)", "", v, flags=re.IGNORECASE)
                out.append((k, v))
            return Reply(resp.status, data, out)
        except (OSError, http.client.HTTPException) as e:
            raise Unreachable(str(e)) from e
        finally:
            conn.close()

    # --- static pages --------------------------------------------------------------------

    def _cache_path(self, path: str) -> Path | None:
        clean = urllib.parse.unquote(path).lstrip("/")
        if not clean or "." not in clean.rsplit("/", 1)[-1]:
            return self.cache / "index.html"  # an SPA route
        parts = [p for p in clean.split("/") if p]
        if any(p in ("..", ".") or "\\" in p or ":" in p for p in parts):
            return None
        return self.cache.joinpath(*parts)

    def _page(self, target: str, h: dict[str, str]) -> Reply:
        path = urllib.parse.urlsplit(target).path
        dest = self._cache_path(path)
        if self.local.server_up():
            try:
                r = self._forward(
                    "GET", target, {"accept": h.get("accept", "*/*")}, b"", self.page_timeout
                )
                self.local.server_ok()
                ctype = next((v for k, v in r.headers if k.lower() == "content-type"), "")
                if r.status == 200 and dest is not None and any(t in ctype for t in STATIC_TYPES):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_suffix(dest.suffix + ".tmp")
                    tmp.write_bytes(r.body)
                    tmp.replace(dest)
                return r
            except Unreachable as e:
                self.local.server_down(str(e))
        if dest is not None and dest.is_file():
            ctype = mimetypes.guess_type(dest.name)[0] or "application/octet-stream"
            if dest.name == "index.html":
                ctype = "text/html; charset=utf-8"
            return Reply(
                200, dest.read_bytes(), [("Content-Type", ctype), ("Cache-Control", "no-store")]
            )
        msg = "سرور در دسترس نیست و این صفحه هنوز روی این صندوق ذخیره نشده است."
        html = f'<!doctype html><meta charset="utf-8"><body dir="rtl"><p>{msg}</p>'
        return Reply(503, html.encode(), [("Content-Type", "text/html; charset=utf-8")])

    # --- api -----------------------------------------------------------------------------

    def _api(self, method: str, target: str, h: dict[str, str], body: bytes) -> Reply:
        path = urllib.parse.urlsplit(target).path
        if self.local.server_up():
            try:
                timeout = (
                    self.api_timeout if path.startswith("/api/v1/sales/") else self.page_timeout
                )
                r = self._forward(method, target, h, body, timeout)
                self.local.server_ok()
                self._observe_auth(method, path, h, r)
                return self._stamp(r, "online")
            except Unreachable as e:
                log.warning("server unreachable for %s %s: %s", method, path, e)
                self.local.server_down(str(e))
        try:
            return self._stamp(self._offline(method, target, h, body), "offline")
        except OfflineError as e:
            return self._stamp(_error(e.status, e.code, e.message), "offline")

    def _cookies(self, h: dict[str, str]) -> dict[str, str]:
        jar = SimpleCookie()
        try:
            jar.load(h.get("cookie", ""))
        except CookieError:
            return {}
        return {k: m.value for k, m in jar.items()}

    def _observe_auth(self, method: str, path: str, h: dict[str, str], r: Reply) -> None:
        """Remember which user each browser session belongs to, for offline selling."""
        store = self.local.store
        sent = self._cookies(h).get(SESSION_COOKIE)
        try:
            if path == "/api/v1/auth/login" and r.status == 200:
                for k, v in r.headers:
                    if k.lower() == "set-cookie" and v.startswith(f"{SESSION_COOKIE}="):
                        token = v.split(";", 1)[0].split("=", 1)[1]
                        if token:
                            store.remember_session(token_hash(token), json.loads(r.body))
            elif path == "/api/v1/auth/me" and r.status == 200 and sent:
                store.remember_session(token_hash(sent), json.loads(r.body))
            elif sent and (path == "/api/v1/auth/logout" or r.status == 401):
                store.forget_session(token_hash(sent))
        except (ValueError, KeyError):
            log.warning("could not read the auth response of %s", path)

    # --- offline -------------------------------------------------------------------------

    def _user(self, h: dict[str, str], method: str) -> tuple[str, dict[str, Any]]:
        cookies = self._cookies(h)
        token = cookies.get(SESSION_COOKIE)
        found = self.local.store.session(token_hash(token)) if token else None
        if found is None:
            raise OfflineError(
                "ابتدا وارد شوید (ورود در حالت آفلاین ممکن نیست)", "not_authenticated", 401
            )
        user_id, me, _ = found
        expires = me.get("session_expires_at")
        if expires and datetime.fromisoformat(expires) < datetime.now(UTC):
            raise OfflineError("نشست شما به پایان رسیده است", "not_authenticated", 401)
        if method not in ("GET", "HEAD"):
            csrf = cookies.get(CSRF_COOKIE)
            if not csrf or h.get("x-csrf-token") != csrf:
                raise OfflineError("توکن CSRF نامعتبر است", "csrf_failed", 403)
        return user_id, me

    def _snap(self) -> Snapshot:
        snap = self.local.snapshot()
        if snap is None:
            raise OfflineError(
                "داده‌های فروش آفلاین هنوز روی این صندوق نیست؛ اتصال به سرور لازم است",
                "offline_unavailable",
                503,
            )
        if not snap.valid():
            raise OfflineError(
                "داده‌های فروش آفلاین این صندوق قدیمی است؛ اتصال به سرور لازم است",
                "offline_unavailable",
                503,
            )
        return snap

    def _offline(self, method: str, target: str, h: dict[str, str], body: bytes) -> Reply:
        parts = urllib.parse.urlsplit(target)
        path, query = parts.path, urllib.parse.parse_qs(parts.query)
        if path == "/api/v1/auth/login":
            raise OfflineError("سرور در دسترس نیست؛ ورود در حالت آفلاین ممکن نیست", "offline", 503)
        user_id, me = self._user(h, method)
        if method == "GET" and path == "/api/v1/auth/me":
            return _json(200, me)
        snap = self._snap()
        reg = snap.register
        data: dict[str, Any] = {}
        if body:
            try:
                data = json.loads(body)
            except ValueError as e:
                raise OfflineError("ورودی نامعتبر است", "validation_error", 400) from e
            if not isinstance(data, dict):
                raise OfflineError("ورودی نامعتبر است", "validation_error", 400)

        route = (method, path)
        if route == ("GET", "/api/v1/organization/branches"):
            return _json(
                200,
                [
                    {
                        "id": reg["branch_id"],
                        "code": "",
                        "name": reg["branch_name"],
                        "address": None,
                        "is_active": True,
                        "row_version": "",
                    }
                ],
            )
        if (
            method == "GET"
            and path == f"/api/v1/organization/branches/{reg['branch_id']}/cash-registers"
        ):
            return _json(
                200,
                [
                    {
                        "id": reg["id"],
                        "branch_id": reg["branch_id"],
                        "code": reg["code"],
                        "name": reg["name"],
                        "is_active": True,
                        "row_version": "",
                    }
                ],
            )
        if method == "GET" and path == f"/api/v1/sales/registers/{reg['id']}/state":
            return _json(200, offline.register_state(snap))
        if route == ("GET", "/api/v1/inventory/items/lookup"):
            return _json(200, offline.lookup(snap, (query.get("barcode") or [""])[0]))
        if route == ("GET", "/api/v1/inventory/items"):
            size = int((query.get("page_size") or ["12"])[0] or 12)
            return _json(
                200, offline.search(snap, (query.get("q") or [""])[0], min(max(size, 1), 50))
            )
        if route == ("GET", "/api/v1/sales/held"):
            return _json(200, [])
        if route == ("POST", "/api/v1/sales/quote"):
            if data.get("cash_register_id") != reg["id"]:
                raise OfflineError(
                    "در حالت آفلاین فقط صندوق همین رایانه در دسترس است", "not_found", 404
                )
            if data.get("customer_id"):
                raise OfflineError("فروش نسیه در حالت آفلاین ممکن نیست", "offline_unsupported")
            return _json(200, offline.quote_view(offline.price(snap, data)))
        if route == ("POST", "/api/v1/sales/invoices"):
            return _json(201, offline.create_sale(self.local.store, snap, user_id, data))
        if route == ("POST", "/api/v1/sales/line-removals"):
            offline.record_removal(self.local.store, snap, user_id, data)
            return _json(201, {"status": "recorded"})
        if method == "GET" and path == f"/api/v1/devices/registers/{reg['id']}":
            printer = self.local.store.get_json("printer") or {}
            has_printer = printer.get("transport", "none") != "none" and self.print_fn is not None
            return _json(
                200,
                {
                    "device_id": self.device_id,
                    "online": has_printer,
                    "printer": has_printer,
                    "drawer": bool(has_printer and printer.get("drawer_enabled")),
                },
            )
        if route == ("POST", "/api/v1/devices/print-receipt"):
            return _json(201, self._print(snap, data))
        if method == "GET" and path.startswith("/api/v1/devices/jobs/"):
            job = self.jobs.get(path.rsplit("/", 1)[-1])
            if job is None:
                raise OfflineError("کار چاپ یافت نشد", "not_found", 404)
            return _json(200, job)
        raise OfflineError(OFFLINE_MESSAGE, "offline", 503)

    def _print(self, snap: Snapshot, data: dict[str, Any]) -> dict[str, Any]:
        sale_id = str(data.get("invoice_id", ""))
        op = self.local.store.op(sale_id)
        if op is None or op.view.get("kind") != "sale":
            raise OfflineError(OFFLINE_MESSAGE, "offline", 503)
        printer = self.local.store.get_json("printer")
        if not printer or printer.get("transport", "none") == "none" or self.print_fn is None:
            raise OfflineError("برای این صندوق چاپگری تنظیم نشده است", "no_printer")
        reprint = bool(data.get("reprint")) or op.printed
        has_cash = any(p["method"] == "cash" for p in op.view["payments"])
        open_drawer = bool(printer.get("drawer_enabled")) and has_cash and not reprint
        paper = data.get("paper", True) is not False
        job: dict[str, Any]
        if paper:
            payload = offline.receipt(
                snap,
                op.view,
                reprint=reprint,
                open_drawer=open_drawer,
                cut=bool(printer.get("cut_paper", True)),
            )
            job = {"id": str(uuid.uuid4()), "kind": "receipt", "payload": payload}
        else:
            if not open_drawer:
                raise OfflineError("کشوی پول برای این فاکتور باز نمی‌شود", "no_drawer")
            job = {
                "id": str(uuid.uuid4()),
                "kind": "drawer",
                "payload": {"pin": printer.get("drawer_pin", 2)},
            }
        started = datetime.now(UTC).isoformat()
        with self._print_lock:
            ok, error = self.print_fn(job, printer)
        if ok or paper:
            self.local.store.mark_printed(sale_id)
        out = {
            "id": job["id"],
            "kind": job["kind"],
            "status": "done" if ok else "failed",
            "error": error,
            "attempts": 1,
            "created_at": started,
            "sent_at": started,
            "finished_at": datetime.now(UTC).isoformat(),
        }
        self.jobs[job["id"]] = out
        if len(self.jobs) > 200:
            self.jobs.pop(next(iter(self.jobs)))
        return out

    # --- the register's own view ---------------------------------------------------------

    def _local(self, method: str, path: str) -> Reply:
        if method != "GET":
            return _error(405, "method", "روش مجاز نیست")
        if path == "/local/status":
            return _json(200, self.local.status(), ("Cache-Control", "no-store"))
        if path == "/local/sales":
            rows = [
                {
                    "id": o.id,
                    "device_number": o.device_number,
                    "created_at": o.created_at,
                    "status": o.status,
                    "number": o.number,
                    "code": o.code,
                    "message": o.message,
                    "grand_total": o.view.get("grand_total"),
                    "kind": o.op["type"],
                }
                for o in self.local.store.ops(limit=100)
            ]
            return _json(200, rows, ("Cache-Control", "no-store"))
        return _error(404, "not_found", "یافت نشد")


# --- HTTP server -------------------------------------------------------------------------


def make_server(gw: Gateway) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "nextcam-gateway"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 5_000_000:
                r = _error(413, "too_large", "درخواست بزرگ است")
            else:
                body = self.rfile.read(length) if length else b""
                try:
                    r = gw.handle(self.command, self.path, dict(self.headers.items()), body)
                except Exception:
                    log.exception("gateway error on %s %s", self.command, self.path)
                    r = _error(500, "internal", "خطای داخلی صندوق")
            self.send_response(r.status)
            for k, v in r.headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(r.body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(r.body)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _serve

        def do_OPTIONS(self) -> None:  # no CORS, ever
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", gw.port), Handler)
    srv.daemon_threads = True
    return srv


def serve_in_background(gw: Gateway) -> ThreadingHTTPServer:
    srv = make_server(gw)
    threading.Thread(target=srv.serve_forever, name="gateway", daemon=True).start()
    return srv
