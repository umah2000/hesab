"""NEXTCAM license tool — FOR THE VENDOR ONLY, on a machine that is not a customer server.

The private key never goes into git, onto a customer server or into a chat. Keep it (and
its passphrase) offline with a backup; anyone holding it can issue licenses.

    # once: a signing key (asks for a passphrase); prints the public key for
    # backend/app/modules/system/license_keys.py
    python nextcam_license.py keygen --out D:\\vault\\nextcam-signing.pem

    # per customer: the request code is shown in the customer's Settings → License
    python nextcam_license.py sign --key D:\\vault\\nextcam-signing.pem \\
        --request NCR1.eyJ... --registers 7 --branches 1 --users 25 \\
        --valid-until 2027-10-19 --support-until 2027-10-19 --feature distribution \\
        --out customer.nclic

    python nextcam_license.py show customer.nclic

License text: ``NCL1.<base64url(payload JSON)>.<base64url(Ed25519 signature of those bytes)>``.
Requires: pip install cryptography
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PREFIX = "NCL1"
REQUEST_PREFIX = "NCR1"
FEATURES = ("distribution",)


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def key_id(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


def public_raw(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def parse_request(code: str) -> dict[str, str]:
    code = "".join(code.split())
    if not code.startswith(REQUEST_PREFIX + "."):
        raise ValueError("not a NEXTCAM activation request code")
    data = json.loads(b64d(code.split(".", 1)[1]))
    uuid.UUID(data["installation_id"])
    return {"installation_id": data["installation_id"], "customer": data["customer"]}


def build_payload(
    request: dict[str, str],
    *,
    kid: str,
    branches: int | None,
    registers: int | None,
    users: int | None,
    features: list[str],
    valid_until: date | None,
    support_until: date | None,
    issued: date,
    note: str | None = None,
) -> dict[str, Any]:
    for f in features:
        if f not in FEATURES:
            raise ValueError(f"unknown feature {f!r}; known: {', '.join(FEATURES)}")
    return {
        "v": 1,
        "kid": kid,
        "license_id": str(uuid.uuid4()),
        "installation_id": request["installation_id"],
        "customer": request["customer"],
        "issued_at": issued.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until else None,
        "support_until": support_until.isoformat() if support_until else None,
        "limits": {"branches": branches, "registers": registers, "users": users},
        "features": sorted(set(features)),
        "note": note,
    }


def sign(key: Ed25519PrivateKey, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return f"{PREFIX}.{b64e(body)}.{b64e(key.sign(body))}"


def load_key(path: str, passphrase: str | None) -> Ed25519PrivateKey:
    data = Path(path).read_bytes()
    key = serialization.load_pem_private_key(
        data, password=passphrase.encode() if passphrase else None
    )
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 key")
    return key


def _passphrase(confirm: bool) -> str:
    env = os.environ.get("NEXTCAM_LICENSE_KEY_PASSPHRASE")
    if env:
        return env
    p = getpass.getpass("passphrase: ")
    if confirm and p != getpass.getpass("again: "):
        raise SystemExit("passphrases differ")
    if len(p) < 12:
        raise SystemExit("use a passphrase of at least 12 characters")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--out", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--key", required=True)
    s.add_argument("--request", required=True)
    s.add_argument("--branches", type=int)
    s.add_argument("--registers", type=int)
    s.add_argument("--users", type=int)
    s.add_argument("--feature", action="append", default=[])
    s.add_argument("--valid-until", type=date.fromisoformat)
    s.add_argument("--support-until", type=date.fromisoformat)
    s.add_argument("--note")
    s.add_argument("--out", required=True)
    sh = sub.add_parser("show")
    sh.add_argument("file")
    a = ap.parse_args(argv)

    if a.cmd == "keygen":
        out = Path(a.out)
        if out.exists():
            raise SystemExit(f"{out} exists; refusing to overwrite a signing key")
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(_passphrase(confirm=True).encode()),
        )
        out.write_bytes(pem)
        raw = public_raw(key)
        print("private key written (encrypted):", out)
        print("add to backend/app/modules/system/license_keys.py TRUSTED:")
        print(f'    "{key_id(raw)}": "{b64e(raw)}",')
        return 0
    if a.cmd == "sign":
        key = load_key(a.key, _passphrase(confirm=False))
        payload = build_payload(
            parse_request(a.request),
            kid=key_id(public_raw(key)),
            branches=a.branches,
            registers=a.registers,
            users=a.users,
            features=a.feature,
            valid_until=a.valid_until,
            support_until=a.support_until,
            issued=date.today(),
            note=a.note,
        )
        Path(a.out).write_text(sign(key, payload) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        print("written:", a.out)
        return 0
    text = Path(a.file).read_text(encoding="utf-8").strip()
    prefix, body, _sig = text.split(".")
    if prefix != PREFIX:
        raise SystemExit("not a NEXTCAM license")
    print(json.dumps(json.loads(b64d(body)), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
