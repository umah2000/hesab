"""Encrypted backup format: round trip and every way a copy can go wrong (no database)."""

from __future__ import annotations

import io
import os
import struct
from pathlib import Path

import pytest

from app.modules.system import backup_crypto as bc


def enc(data: bytes, key: bytes, chunk: int = 1000) -> bytes:
    out = io.BytesIO()
    bc.encrypt_stream(io.BytesIO(data), out, key, chunk=chunk)
    return out.getvalue()


def dec(blob: bytes, key: bytes) -> bytes:
    out = io.BytesIO()
    bc.decrypt_stream(io.BytesIO(blob), out, key)
    return out.getvalue()


KEY = bc.parse_key(bc.generate_key())


@pytest.mark.parametrize("size", [0, 1, 999, 1000, 1001, 5000, 12345])
def test_round_trip(size: int) -> None:
    data = os.urandom(size)
    blob = enc(data, KEY)
    assert dec(blob, KEY) == data
    # Never stored in the clear. Only meaningful for longer data: a 1-byte value turns up
    # by chance in ~60 random ciphertext bytes about 20% of the time (seen on CI).
    if size >= 16:
        assert data not in blob


def test_digest_is_of_the_plaintext(tmp_path: Path) -> None:
    src = tmp_path / "x.bak"
    src.write_bytes(os.urandom(3 * 1024 * 1024 + 7))
    digest = bc.encrypt_file(src, tmp_path / "x.bak.ncbk", KEY)
    assert digest == bc.sha256_file(src)
    assert bc.decrypt_file(tmp_path / "x.bak.ncbk", None, KEY) == digest
    assert bc.decrypt_file(tmp_path / "x.bak.ncbk", tmp_path / "y.bak", KEY) == digest
    assert (tmp_path / "y.bak").read_bytes() == src.read_bytes()
    assert not list(tmp_path.glob("*.partial"))


def test_wrong_key_damage_truncation_and_reordering() -> None:
    data = os.urandom(4500)
    blob = enc(data, KEY)
    other = bc.parse_key(bc.generate_key())
    with pytest.raises(bc.BackupCryptoError, match="کلید دیگری"):
        dec(blob, other)

    flipped = bytearray(blob)
    flipped[200] ^= 1
    with pytest.raises(bc.BackupCryptoError, match="آسیب"):
        dec(bytes(flipped), KEY)

    # Chunks: header, then (len, ct) pairs. Cut after the second chunk: the last-chunk flag
    # in the authenticated data no longer matches, so a short copy never "restores".
    h = bc.HEADER.size
    first = struct.unpack(">I", blob[h : h + 4])[0]
    second_at = h + 4 + first
    second = struct.unpack(">I", blob[second_at : second_at + 4])[0]
    cut = blob[: second_at + 4 + second]
    with pytest.raises(bc.BackupCryptoError):
        dec(cut, KEY)
    with pytest.raises(bc.BackupCryptoError, match="ناقص"):
        dec(blob[:-5], KEY)

    # Swap chunks 1 and 2 (same length): nonce/index binding rejects it.
    c1 = blob[h:second_at]
    c2 = blob[second_at : second_at + 4 + second]
    swapped = blob[:h] + c2 + c1 + blob[second_at + 4 + second :]
    with pytest.raises(bc.BackupCryptoError):
        dec(swapped, KEY)

    with pytest.raises(bc.BackupCryptoError, match="NEXTCAM نیست"):
        dec(b"MSSQLBAK" + os.urandom(100), KEY)


def test_keys() -> None:
    assert len(bc.parse_key(bc.generate_key())) == 32
    for bad in ("", "abc", bc.generate_key()[:-8]):
        with pytest.raises(bc.BackupCryptoError):
            bc.parse_key(bad)


def test_recovery_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    text = bc.generate_key()
    src = tmp_path / "a.bak"
    src.write_bytes(b"backup" * 1000)
    bc.encrypt_file(src, tmp_path / "a.bak.ncbk", bc.parse_key(text))
    monkeypatch.delenv("NEXTCAM_BACKUP_KEY", raising=False)
    assert bc.main(["decrypt", str(tmp_path / "a.bak.ncbk"), str(tmp_path / "b.bak")]) == 2
    monkeypatch.setenv("NEXTCAM_BACKUP_KEY", text)
    assert bc.main(["verify", str(tmp_path / "a.bak.ncbk")]) == 0
    assert bc.main(["decrypt", str(tmp_path / "a.bak.ncbk"), str(tmp_path / "b.bak")]) == 0
    assert (tmp_path / "b.bak").read_bytes() == src.read_bytes()
    monkeypatch.setenv("NEXTCAM_BACKUP_KEY", bc.generate_key())
    assert bc.main(["verify", str(tmp_path / "a.bak.ncbk")]) == 1
    assert "کلید دیگری" in capsys.readouterr().err
