"""Rate limiting for sensitive endpoints.

In-memory storage is correct for the single-process Windows service deployment;
a multi-process deployment needs a shared storage URI.
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri="memory://", default_limits=[])
