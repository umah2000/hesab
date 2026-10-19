"""Encrypted backup files (phase 10): AES-256-GCM in authenticated chunks.

A backup copied off the server (USB disk, network share, cloud-synced folder) holds the
whole database, so it leaves the machine only encrypted. The key comes from the
environment (``NEXTCAM_BACKUP_KEY``, 32 random bytes in URL-safe base64); without it a copy
cannot be read, so it must also be kept somewhere safe outside the server.

File layout (``.ncbk``)::

    header  = b"NCBK" | version (1) | key id (8) | chunk size (4, BE) | nonce prefix (8)
    chunk*  = ciphertext length (4, BE) | AES-GCM(ciphertext + tag)

Chunk ``i`` uses nonce ``prefix | i`` and authenticates ``header | i | last-flag``, so a
copy that was cut short, reordered or spliced from another file does not decrypt. The key
id (first 8 bytes of SHA-256 of the key) tells a wrong key apart from a damaged file.

Disaster recovery without a configured server (only the key in the environment)::

    python -m app.modules.system.backup_crypto decrypt nextcam_X.bak.ncbk nextcam_X.bak
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import struct
import sys
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"NCBK"
VERSION = 1
CHUNK = 4 * 1024 * 1024
HEADER = struct.Struct(">4sB8sI8s")
SUFFIX = ".ncbk"


class BackupCryptoError(Exception):
    """Wrong key, damaged or truncated file. The message is safe to show."""


def generate_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def parse_key(text: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(text.strip().encode() + b"=" * (-len(text.strip()) % 4))
    except ValueError as e:
        raise BackupCryptoError("کلید پشتیبان معتبر نیست (base64)") from e
    if len(raw) != 32:
        raise BackupCryptoError("کلید پشتیبان باید ۳۲ بایت باشد")
    return raw


def key_id(key: bytes) -> bytes:
    return hashlib.sha256(key).digest()[:8]


def _aad(header: bytes, index: int, last: bool) -> bytes:
    return header + struct.pack(">I?", index, last)


def encrypt_stream(src: BinaryIO, dst: BinaryIO, key: bytes, chunk: int = CHUNK) -> str:
    """Encrypt ``src`` into ``dst``; returns the SHA-256 (hex) of the plaintext."""
    aes = AESGCM(key)
    prefix = secrets.token_bytes(8)
    header = HEADER.pack(MAGIC, VERSION, key_id(key), chunk, prefix)
    dst.write(header)
    digest = hashlib.sha256()
    index = 0
    block = src.read(chunk)
    while True:
        nxt = src.read(chunk) if block else b""
        last = not nxt
        digest.update(block)
        ct = aes.encrypt(prefix + struct.pack(">I", index), block, _aad(header, index, last))
        dst.write(struct.pack(">I", len(ct)) + ct)
        if last:
            return digest.hexdigest()
        block, index = nxt, index + 1
        if index >= 2**32 - 1:
            raise BackupCryptoError("فایل برای این قالب بیش از حد بزرگ است")


def _read_exact(f: BinaryIO, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise BackupCryptoError("فایل پشتیبان ناقص است")
    return data


def decrypt_stream(src: BinaryIO, dst: BinaryIO | None, key: bytes) -> str:
    """Decrypt into ``dst`` (or only verify when None); returns the plaintext SHA-256."""
    header = src.read(HEADER.size)
    if len(header) != HEADER.size:
        raise BackupCryptoError("این فایل پشتیبان رمزنگاری‌شده NEXTCAM نیست")
    magic, version, kid, chunk, prefix = HEADER.unpack(header)
    if magic != MAGIC:
        raise BackupCryptoError("این فایل پشتیبان رمزنگاری‌شده NEXTCAM نیست")
    if version != VERSION:
        raise BackupCryptoError("نسخه‌ی قالب فایل پشتیبان پشتیبانی نمی‌شود")
    if kid != key_id(key):
        raise BackupCryptoError("این فایل با کلید دیگری رمزنگاری شده است")
    aes = AESGCM(key)
    digest = hashlib.sha256()
    index = 0
    size = src.read(4)
    if len(size) != 4:
        raise BackupCryptoError("فایل پشتیبان ناقص است")
    while True:
        (n,) = struct.unpack(">I", size)
        if n > chunk + 16:
            raise BackupCryptoError("فایل پشتیبان آسیب دیده است")
        ct = _read_exact(src, n)
        size = src.read(4)
        last = not size
        if size and len(size) != 4:
            raise BackupCryptoError("فایل پشتیبان ناقص است")
        try:
            block = aes.decrypt(prefix + struct.pack(">I", index), ct, _aad(header, index, last))
        except InvalidTag as e:
            raise BackupCryptoError("فایل پشتیبان آسیب دیده یا ناقص است") from e
        digest.update(block)
        if dst is not None:
            dst.write(block)
        if last:
            return digest.hexdigest()
        index += 1


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def encrypt_file(src: str | Path, dst: str | Path, key: bytes) -> str:
    """Write ``dst`` atomically (temp name, then rename); returns the plaintext SHA-256."""
    tmp = Path(str(dst) + ".partial")
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            digest = encrypt_stream(fi, fo, key)
            fo.flush()
            os.fsync(fo.fileno())
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return digest


def decrypt_file(src: str | Path, dst: str | Path | None, key: bytes) -> str:
    if dst is None:
        with open(src, "rb") as fi:
            return decrypt_stream(fi, None, key)
    tmp = Path(str(dst) + ".partial")
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            digest = decrypt_stream(fi, fo, key)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return digest


def main(argv: list[str]) -> int:
    usage = "usage: python -m app.modules.system.backup_crypto decrypt|verify <in.ncbk> [out.bak]"
    if len(argv) < 2 or argv[0] not in ("decrypt", "verify"):
        print(usage, file=sys.stderr)
        return 2
    text = os.environ.get("NEXTCAM_BACKUP_KEY")
    if not text:
        print("NEXTCAM_BACKUP_KEY is not set", file=sys.stderr)
        return 2
    try:
        key = parse_key(text)
        if argv[0] == "verify":
            print("ok sha256=" + decrypt_file(argv[1], None, key))
        else:
            if len(argv) < 3:
                print(usage, file=sys.stderr)
                return 2
            print("ok sha256=" + decrypt_file(argv[1], argv[2], key))
    except BackupCryptoError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
