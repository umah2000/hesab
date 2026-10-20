"""Keeps the register's local data in step with the server (ADR-0017).

* Pulls the snapshot (ETag: unchanged costs a 304) every minute and after each push.
* Pushes queued offline sales in order, 50 at a time. The server answers each one
  (applied, conflict, rejected); only then does it leave the queue. Nothing is retried
  differently or dropped on the register: conflicts are for a person on the server.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from nextcam_agent.client import ServerClient, ServerError, Unauthorized
from nextcam_agent.offline import Snapshot
from nextcam_agent.store import Store, now_iso

log = logging.getLogger("nextcam_agent.sync")
BATCH = 50
RETRY_AFTER = 5.0  # a failed server is tried again after this many seconds


class Local:
    """What the gateway, the syncer and the poller share on this register."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._snap: Snapshot | None = None
        self._lock = threading.Lock()
        self.last_ok: float | None = None
        self.last_fail: float | None = None
        self.last_sync_at: str | None = store.get("last_sync_at")
        self.last_error: str | None = None
        raw = store.get_json("snapshot")
        if raw is not None:
            self._snap = Snapshot(raw, store.get("snapshot_fetched_at"))

    # --- server reachability -----------------------------------------------------------

    def server_ok(self) -> None:
        self.last_ok, self.last_error = time.monotonic(), None

    def server_down(self, error: str) -> None:
        self.last_fail, self.last_error = time.monotonic(), error[:200]

    def server_up(self) -> bool:
        """Worth trying the server now? After a failure, only once RETRY_AFTER has passed
        (the poller probes every second, so recovery is noticed quickly)."""
        if self.last_fail is None:
            return True
        if self.last_ok is not None and self.last_ok > self.last_fail:
            return True
        return time.monotonic() - self.last_fail >= RETRY_AFTER

    @property
    def online(self) -> bool:
        return self.last_ok is not None and (
            self.last_fail is None or self.last_ok > self.last_fail
        )

    # --- snapshot ----------------------------------------------------------------------

    def snapshot(self) -> Snapshot | None:
        snap = self._snap
        if snap is not None:
            snap.with_unsettled(self.store.unsettled_stock(snap.fetched_at))
        return snap

    def set_snapshot(self, raw: dict[str, Any], etag: str | None, fetched_at: str) -> None:
        snap = Snapshot(raw, fetched_at)  # parse before storing: never keep a broken one
        values = {
            "snapshot": json.dumps(raw, ensure_ascii=False),
            "snapshot_etag": etag or "",
            "snapshot_fetched_at": fetched_at,
        }
        with self.store.tx() as db:
            for k, v in values.items():
                db.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, v),
                )
        with self._lock:
            self._snap = snap

    def touch_snapshot(self, fetched_at: str) -> None:
        """Unchanged content (304): it is still the server's current view."""
        self.store.put("snapshot_fetched_at", fetched_at)
        snap = self._snap
        if snap is not None:
            snap.fetched_at = fetched_at

    def status(self) -> dict[str, Any]:
        snap = self._snap
        counts = self.store.counts()
        now = datetime.now(UTC)
        return {
            "mode": "online" if self.online else "offline",
            "last_error": self.last_error,
            "last_sync_at": self.last_sync_at,
            "snapshot": None
            if snap is None
            else {
                "version": snap.version,
                "fetched_at": snap.fetched_at,
                "valid_until": snap.valid_until.isoformat(),
                "valid": snap.valid(now),
            },
            "register_id": snap.register["id"] if snap else None,
            "shift": None
            if snap is None or snap.shift is None
            else {
                "id": snap.shift["id"],
                "user_id": snap.shift["user_id"],
                "user_name": snap.shift["user_name"],
            },
            "can_sell_offline": bool(snap and snap.valid(now) and snap.shift),
            "queue": {
                "pending": counts.get("pending", 0),
                "conflict": counts.get("conflict", 0),
                "rejected": counts.get("rejected", 0),
                "synced": counts.get("applied", 0) + counts.get("resolved", 0),
            },
        }


class Syncer:
    def __init__(
        self,
        local: Local,
        client: ServerClient,
        *,
        interval: float = 3.0,
        snapshot_every: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.local, self.client = local, client
        self.interval, self.snapshot_every = interval, snapshot_every
        self._last_pull = 0.0
        self.stopped_reason: str | None = None

    def pull(self) -> bool:
        """Fetch the snapshot; True when it changed."""
        started = now_iso()
        etag = self.local.store.get("snapshot_etag") or None
        if self.local.snapshot() is None:
            etag = None
        raw, tag = self.client.snapshot(etag)
        self._last_pull = time.monotonic()
        if raw is None:
            self.local.touch_snapshot(started)
            return False
        self.local.set_snapshot(raw, tag, started)
        log.info("snapshot %s (%d items)", raw.get("version"), len(raw.get("items", [])))
        return True

    def push(self) -> int:
        """Send queued operations; returns how many the server answered."""
        store = self.local.store
        answered = 0
        while True:
            ops = store.ops("pending", limit=BATCH)
            if not ops:
                break
            results = self.client.push([o.op for o in ops])
            for o, r in zip(ops, results, strict=False):
                store.record_result(
                    o.id, r["status"], r.get("number"), r.get("code"), r.get("message")
                )
                if r["status"] in ("conflict", "rejected"):
                    log.warning(
                        "offline %s %s: %s %s",
                        o.device_number,
                        r["status"],
                        r.get("code"),
                        r.get("message"),
                    )
            answered += len(results)
            if len(results) < len(ops):
                break
        if answered:
            self.local.last_sync_at = now_iso()
            store.put("last_sync_at", self.local.last_sync_at)
        return answered

    def step(self) -> None:
        pushed = self.push()
        if pushed or time.monotonic() - self._last_pull >= self.snapshot_every:
            self.pull()
        self.local.server_ok()

    def run(self, stop: threading.Event) -> None:
        backoff = self.interval
        while not stop.is_set():
            try:
                self.step()
                backoff = self.interval
            except Unauthorized:
                # Keep every queued sale: re-pair this same device (pairing code from the
                # device page) and the queue is sent with the new token.
                self.stopped_reason = "توکن دستگاه باطل شده؛ فروش‌های آفلاین نگه داشته شده‌اند"
                log.error("sync stopped: device token rejected")
                return
            except (ServerError, OSError, ValueError, KeyError) as e:
                self.local.server_down(str(e))
                backoff = min(backoff * 2, 30.0)
                log.info("sync waiting: %s", e)
            stop.wait(backoff)
