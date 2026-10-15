"""The register's local database (SQLite, WAL, synchronous=FULL) — ADR-0017.

Holds what keeps the register selling when the server is unreachable, and the sales
made meanwhile until the server has acknowledged each one:

* ``meta``: the snapshot (catalogue, prices, open shift), its ETag, the printer
  settings and the receipt-number sequence;
* ``sessions``: hashes of browser session cookies the server accepted, with the user
  they belong to (offline, only the cashier of the open shift can sell);
* ``ops``: offline sales. Nothing here is deleted while it is pending; a sale leaves the
  queue only when the server has answered for it (applied, conflict or rejected).

One connection guarded by a lock: the gateway, the syncer and the poller share it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, me TEXT NOT NULL, seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ops (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL UNIQUE,
    device_number TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    -- pending → applied | resolved | conflict | rejected (answered by the server)
    status TEXT NOT NULL DEFAULT 'pending',
    op TEXT NOT NULL,          -- what is pushed (sync protocol)
    view TEXT NOT NULL,        -- the invoice as the POS and the receipt show it
    stock TEXT NOT NULL,       -- {item_id: base qty} taken out of local stock
    printed INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT,
    number INTEGER,
    code TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS ix_ops_status ON ops (status, seq);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Op:
    id: str
    seq: int
    device_number: str
    created_at: str
    status: str
    op: dict[str, Any]
    view: dict[str, Any]
    stock: dict[str, str]
    printed: bool
    synced_at: str | None
    number: int | None
    code: str | None
    message: str | None


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            # A sale handed to the customer must survive a power cut.
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    # --- meta -----------------------------------------------------------------------

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def put(self, key: str, value: str) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_json(self, key: str) -> Any:
        raw = self.get(key)
        return None if raw is None else json.loads(raw)

    def put_json(self, key: str, value: Any) -> None:
        self.put(key, json.dumps(value, ensure_ascii=False))

    # --- sessions -------------------------------------------------------------------

    def remember_session(self, token_hash: str, me: dict[str, Any]) -> None:
        with self.tx() as db:
            db.execute(
                "INSERT INTO sessions (hash, user_id, me, seen_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(hash) DO UPDATE SET user_id = excluded.user_id, "
                "me = excluded.me, seen_at = excluded.seen_at",
                (token_hash, str(me["id"]), json.dumps(me, ensure_ascii=False), now_iso()),
            )

    def session(self, token_hash: str) -> tuple[str, dict[str, Any], str] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT user_id, me, seen_at FROM sessions WHERE hash = ?", (token_hash,)
            ).fetchone()
        return None if row is None else (row["user_id"], json.loads(row["me"]), row["seen_at"])

    def forget_session(self, token_hash: str) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM sessions WHERE hash = ?", (token_hash,))

    # --- offline sales --------------------------------------------------------------

    def next_seq(self, db: sqlite3.Connection) -> int:
        row = db.execute("SELECT value FROM meta WHERE key = 'seq'").fetchone()
        seq = int(row["value"]) + 1 if row else 1
        db.execute(
            "INSERT INTO meta (key, value) VALUES ('seq', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(seq),),
        )
        return seq

    def add_op(
        self,
        db: sqlite3.Connection,
        *,
        op_id: str,
        seq: int,
        device_number: str,
        op: dict[str, Any],
        view: dict[str, Any],
        stock: dict[str, str],
    ) -> None:
        db.execute(
            "INSERT INTO ops (id, seq, device_number, created_at, op, view, stock) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                op_id,
                seq,
                device_number,
                now_iso(),
                json.dumps(op, ensure_ascii=False),
                json.dumps(view, ensure_ascii=False),
                json.dumps(stock),
            ),
        )

    @staticmethod
    def _op(row: sqlite3.Row) -> Op:
        return Op(
            id=row["id"],
            seq=row["seq"],
            device_number=row["device_number"],
            created_at=row["created_at"],
            status=row["status"],
            op=json.loads(row["op"]),
            view=json.loads(row["view"]),
            stock=json.loads(row["stock"]),
            printed=bool(row["printed"]),
            synced_at=row["synced_at"],
            number=row["number"],
            code=row["code"],
            message=row["message"],
        )

    def op(self, op_id: str) -> Op | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM ops WHERE id = ?", (op_id,)).fetchone()
        return None if row is None else self._op(row)

    def ops(self, status: str | None = None, limit: int = 200) -> list[Op]:
        with self._lock:
            if status:
                rows = self._db.execute(
                    "SELECT * FROM ops WHERE status = ? ORDER BY seq LIMIT ?", (status, limit)
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM ops ORDER BY seq DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._op(r) for r in rows]

    def pending_count(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) AS n FROM ops WHERE status = 'pending'")
            return int(row.fetchone()["n"])

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT status, COUNT(*) AS n FROM ops GROUP BY status")
            return {r["status"]: int(r["n"]) for r in rows.fetchall()}

    def mark_printed(self, op_id: str) -> None:
        with self.tx() as db:
            db.execute("UPDATE ops SET printed = 1 WHERE id = ?", (op_id,))

    def record_result(
        self,
        op_id: str,
        status: str,
        number: int | None,
        code: str | None,
        message: str | None,
    ) -> None:
        with self.tx() as db:
            db.execute(
                "UPDATE ops SET status = ?, number = ?, code = ?, message = ?, synced_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, number, code, message, now_iso(), op_id),
            )

    def unsettled_stock(self, since: str | None) -> dict[str, list[str]]:
        """Base quantities sold here that the last snapshot does not reflect yet:
        pending sales, and those the server accepted after the snapshot was taken."""
        with self._lock:
            rows = self._db.execute(
                "SELECT stock FROM ops WHERE status = 'pending' "
                "OR (status IN ('applied', 'resolved') AND (? IS NULL OR synced_at > ?))",
                (since, since),
            ).fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            for item_id, q in json.loads(r["stock"]).items():
                out.setdefault(item_id, []).append(q)
        return out
