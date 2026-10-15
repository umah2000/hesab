"""The agent loop: poll the server, run one job at a time, report the result.

Rules (ADR-0015):
* a job is executed at most once by this agent, even if the result cannot be reported
  (the server then marks it expired and the cashier checks the paper);
* nothing is retried automatically — a second receipt or drawer pulse is worse than none;
* the printer state sent with every poll is informational only.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from nextcam_agent import escpos, transports
from nextcam_agent.client import ServerClient, ServerError, Unauthorized
from nextcam_agent.config import AgentConfig
from nextcam_agent.render import receipt_image

log = logging.getLogger("nextcam_agent")
MAX_BACKOFF = 10.0


@dataclass
class Status:
    connected: bool = False
    paired: bool = True
    printer_state: str | None = None
    last_poll_at: str | None = None
    last_error: str | None = None
    recent_jobs: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=20))


class Agent:
    def __init__(
        self,
        cfg: AgentConfig,
        client: ServerClient,
        make_transport: Callable[[str, str | None], transports.Transport] = transports.make,
    ) -> None:
        self.cfg, self.client, self.make_transport = cfg, client, make_transport
        self.status = Status()
        self._done: deque[str] = deque(maxlen=500)
        self._lock = threading.Lock()

    # --- one iteration ------------------------------------------------------------

    def step(self) -> bool:
        """Poll once; returns True when a job was handled."""
        with self._lock:
            resp = self.client.poll(self.status.printer_state)
            self.status.connected = True
            self.status.last_poll_at = datetime.now(UTC).isoformat(timespec="seconds")
            job = resp.get("job")
            if not job or job["id"] in self._done:
                return False
            self._done.append(job["id"])
            ok, error = self.execute(job, resp["printer"])
            self.status.printer_state = "ok" if ok else error
            self.status.recent_jobs.appendleft(
                {
                    "id": job["id"],
                    "kind": job["kind"],
                    "ok": ok,
                    "error": error,
                    "at": self.status.last_poll_at,
                }
            )
            for attempt in range(3):
                try:
                    self.client.result(job["id"], ok, error)
                    break
                except ServerError as e:
                    if e.status in (404, 409):
                        break  # closed on the server (expired); nothing to retry
                    time.sleep(0.5 * (attempt + 1))
                except OSError:
                    time.sleep(0.5 * (attempt + 1))
            return True

    def execute(self, job: dict[str, Any], printer: dict[str, Any]) -> tuple[bool, str | None]:
        try:
            data = self.build(job, printer)
            transport, address = printer["transport"], printer.get("address")
            if self.cfg.printer_override:
                transport, _, address = self.cfg.printer_override.partition(":")
            self.make_transport(transport, address).send(data)
            log.info("job %s (%s) printed", job["id"], job["kind"])
            return True, None
        except transports.PrinterError as e:
            log.warning("job %s failed: %s", job["id"], e)
            return False, str(e)[:300]
        except Exception:
            log.exception("job %s crashed", job["id"])
            return False, "خطای داخلی Device Agent؛ گزارش را بررسی کنید"

    @staticmethod
    def build(job: dict[str, Any], printer: dict[str, Any]) -> bytes:
        kind, payload = job["kind"], job["payload"]
        if kind == "drawer":
            return escpos.INIT + escpos.drawer_kick(int(payload.get("pin", printer["drawer_pin"])))
        if kind in ("receipt", "test"):
            image = receipt_image(payload, int(printer["paper_width"]))
            pin = (
                printer["drawer_pin"]
                if payload.get("open_drawer") and printer["drawer_enabled"]
                else None
            )
            return escpos.receipt_bytes(
                image, cut_paper=bool(payload.get("cut", printer["cut_paper"])), drawer_pin=pin
            )
        raise transports.PrinterError(f"نوع کار ناشناخته: {kind}")

    # --- loop -----------------------------------------------------------------------

    def run(self, stop: threading.Event) -> None:
        backoff = self.cfg.poll_interval
        while not stop.is_set():
            try:
                busy = self.step()
                backoff = self.cfg.poll_interval
                if busy:
                    continue
            except Unauthorized:
                self.status.connected, self.status.paired = True, False
                self.status.last_error = "توکن دستگاه باطل شده؛ دوباره جفت‌سازی کنید"
                log.error("device token rejected; pairing required")
                return
            except (ServerError, OSError, ValueError) as e:
                self.status.connected = False
                self.status.last_error = str(e)[:200]
                log.warning("server unreachable: %s", e)
                backoff = min(backoff * 2, MAX_BACKOFF)
            stop.wait(backoff)

    def snapshot(self) -> dict[str, Any]:
        s = self.status
        return {
            "device": self.cfg.device_name,
            "server": self.cfg.server_url,
            "connected": s.connected,
            "paired": s.paired,
            "printer_state": s.printer_state,
            "last_poll_at": s.last_poll_at,
            "last_error": s.last_error,
            "recent_jobs": list(s.recent_jobs),
        }
