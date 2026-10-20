"""Small in-process cache for reference data read on every scan (ADR-0013).

Registers, the organization's sales settings, the default price list, units and scale
prefixes change rarely but were read by every lookup and quote. Values are immutable
snapshots (never ORM objects). Entries expire after ``TTL``; a service that changes
the underlying rows calls ``invalidate_after_commit`` so the change shows at once.
Single-process deployment (like the rate limiter and the session cache).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy import event
from sqlalchemy.orm import Session

T = TypeVar("T")
TTL = 30.0
_data: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def get(key: str, load: Callable[[], T]) -> T:
    now = time.monotonic()
    with _lock:
        hit = _data.get(key)
    if hit is not None and now - hit[0] < TTL:
        value: T = hit[1]
        return value
    value = load()
    with _lock:
        _data[key] = (now, value)
    return value


def clear() -> None:
    with _lock:
        _data.clear()


def invalidate_after_commit(s: Session) -> None:
    clear()
    s.info["refcache_clear"] = True


@event.listens_for(Session, "after_commit")
def _after_commit(s: Session) -> None:
    if s.info.pop("refcache_clear", False):
        clear()
