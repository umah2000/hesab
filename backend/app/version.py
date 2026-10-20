"""Release identity. Bumped by tools/release/build_release.py; see docs/install/upgrade.md."""

from __future__ import annotations

from datetime import date

VERSION = "1.0.0"
# A license whose support ends before this date does not cover this release (ADR-0021).
RELEASED = date(2026, 10, 19)
