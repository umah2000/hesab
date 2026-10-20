"""Public keys whose signatures make a license valid (ADR-0021).

Public keys are not secret. The matching private key belongs to the vendor alone and is
created with ``tools/license/nextcam_license.py keygen`` on the vendor's own machine;
it never enters this repository. Until the vendor adds a key here, no license verifies
and installations run as "unlicensed" (a warning only; see docs/install/license.md).
"""

from __future__ import annotations

# key id (first 16 hex of SHA-256 of the raw key) -> raw Ed25519 public key, base64url
TRUSTED: dict[str, str] = {}
