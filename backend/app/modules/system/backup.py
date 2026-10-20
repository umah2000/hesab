"""Database backup, verification and restore test (phase 4, risk R2 / Q13).

The application (1) writes a checksummed backup on a schedule, (2) proves it can be
restored, and (3) nags the manager when the last copy taken off the machine is too old.
Phase 10: with ``backup_copy_dir`` and ``backup_key`` every backup is also encrypted
(backup_crypto, AES-256-GCM), copied to that second destination, decrypted again to
check it, and recorded as the offsite copy; the restore test then uses that copy.
All SQL takes names and paths as parameters or through QUOTENAME.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import utcnow
from app.modules.organization.models import Organization
from app.modules.system import backup_crypto
from app.modules.system.models import BackupLog

PREFIX = "nextcam_"


def _exec(engine: Engine, sql: str, *params: object) -> list[tuple[Any, ...]]:
    # BACKUP/RESTORE cannot run inside a transaction; SQLAlchemy restores the pooled
    # connection's isolation level when it is returned.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        dbapi = conn.connection.driver_connection
        assert dbapi is not None
        cur = dbapi.cursor()
        try:
            cur.execute(sql, params)
            rows: list[tuple[Any, ...]] = []
            while True:
                if cur.description is not None:
                    rows.extend(tuple(r) for r in cur.fetchall())
                if not cur.nextset():
                    break
            return rows
        finally:
            cur.close()


def _folder(engine: Engine, settings: Settings) -> str:
    if settings.backup_dir:
        return settings.backup_dir.rstrip("/\\")
    rows = _exec(
        engine, "SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(400))"
    )
    return str(rows[0][0]).rstrip("/\\")


def _join(folder: str, name: str) -> str:
    sep = "\\" if "\\" in folder or (len(folder) > 1 and folder[1] == ":") else "/"
    return f"{folder}{sep}{name}"


def _name(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _readable(settings: Settings, folder: str, name: str) -> Path:
    """The backup folder as this program sees it (same path, or backup_read_dir)."""
    return Path(settings.backup_read_dir or folder) / name


@dataclass(frozen=True)
class CopyResult:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class BackupResult:
    path: str
    size_bytes: int | None
    verified: bool
    copy: CopyResult | None = None


def _log(
    engine: Engine,
    kind: str,
    status: str,
    started: datetime,
    *,
    path: str | None = None,
    size: int | None = None,
    verified: bool = False,
    message: str | None = None,
) -> None:
    with Session(engine) as s, s.begin():
        s.add(
            BackupLog(
                kind=kind,
                status=status,
                started_at=started,
                finished_at=utcnow(),
                file_path=path,
                size_bytes=size,
                verified=verified,
                message=(message or "")[:1000] or None,
            )
        )


def run_backup(engine: Engine, settings: Settings) -> BackupResult:
    started = utcnow()
    path: str | None = None
    try:
        folder = _folder(engine, settings)
        path = _join(folder, f"{PREFIX}{started.strftime('%Y%m%d_%H%M%S')}.bak")
        express = _exec(engine, "SELECT CAST(SERVERPROPERTY('EngineEdition') AS int)")[0][0] == 4
        options = "CHECKSUM, INIT" + ("" if express else ", COMPRESSION")
        db = _exec(engine, "SELECT DB_NAME()")[0][0]
        _exec(
            engine,
            f"DECLARE @db sysname = ?; BACKUP DATABASE @db TO DISK = ? WITH {options}",
            db,
            path,
        )
        _exec(engine, "RESTORE VERIFYONLY FROM DISK = ? WITH CHECKSUM", path)
        size_rows = _exec(
            engine,
            "SELECT TOP 1 COALESCE(b.compressed_backup_size, b.backup_size) "
            "FROM msdb.dbo.backupset b JOIN msdb.dbo.backupmediafamily m "
            "ON m.media_set_id = b.media_set_id "
            "WHERE m.physical_device_name = ? ORDER BY b.backup_finish_date DESC",
            path,
        )
        size = int(size_rows[0][0]) if size_rows and size_rows[0][0] is not None else None
        _prune(folder, settings.backup_keep)
    except Exception as e:
        _log(engine, "backup", "failed", started, path=path, message=_short(e))
        raise
    _log(engine, "backup", "ok", started, path=path, size=size, verified=True)
    copy = None
    if settings.backup_copy_dir:
        # A failed copy fails the command (Task Scheduler shows it) but the backup stands.
        copy = copy_encrypted(engine, settings, _readable(settings, folder, _name(path)))
    return BackupResult(path, size, True, copy)


def _key(settings: Settings) -> bytes:
    if settings.backup_key is None:
        raise RuntimeError("کلید رمزنگاری پشتیبان (NEXTCAM_BACKUP_KEY) تنظیم نشده است")
    return backup_crypto.parse_key(settings.backup_key.get_secret_value())


def copy_encrypted(engine: Engine, settings: Settings, source: Path) -> CopyResult:
    """Encrypt ``source`` into the copy folder, decrypt it back to compare, record it."""
    started = utcnow()
    assert settings.backup_copy_dir
    dest = Path(settings.backup_copy_dir) / (source.name + backup_crypto.SUFFIX)
    try:
        key = _key(settings)
        dest.parent.mkdir(parents=True, exist_ok=True)
        digest = backup_crypto.encrypt_file(source, dest, key)
        # Read back from the destination: proves the copy, the key and the medium.
        if backup_crypto.decrypt_file(dest, None, key) != digest:
            raise RuntimeError("نسخه رمزنگاری‌شده با فایل پشتیبان یکسان نیست")
        size = dest.stat().st_size
        _prune_copies(Path(settings.backup_copy_dir), settings.backup_copy_keep)
    except Exception as e:
        _log(engine, "copy", "failed", started, path=str(dest), message=_short(e))
        raise
    with Session(engine) as s, s.begin():
        mark_offsite(s)
    _log(
        engine,
        "copy",
        "ok",
        started,
        path=str(dest),
        size=size,
        verified=True,
        message=f"sha256={digest}",
    )
    return CopyResult(str(dest), size, digest)


def _prune_copies(folder: Path, keep: int) -> None:
    if keep < 1:
        return
    files = sorted(
        folder.glob(f"{PREFIX}*.bak{backup_crypto.SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def _prune(folder: str, keep: int) -> None:
    """Only when the backup folder is on this machine (the usual single-server install)."""
    d = Path(folder)
    if keep < 1 or not d.is_dir():
        return
    files = sorted(d.glob(f"{PREFIX}*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def restore_test(engine: Engine, settings: Settings, path: str | None = None) -> dict[str, Any]:
    """Restore the newest (or given) backup under a scratch name, check it, drop it.

    With encrypted copies configured the newest copy is tested (decrypted next to the
    backups, restored, then deleted): that is the file a disaster recovery would use.
    """
    started = utcnow()
    scratch = None
    plain: Path | None = None
    tested: str | None = path
    try:
        if path is None:
            kinds = ("copy", "backup") if settings.backup_copy_dir else ("backup",)
            with Session(engine) as s:
                for kind in kinds:
                    path = s.scalar(
                        select(BackupLog.file_path)
                        .where(BackupLog.kind == kind, BackupLog.status == "ok")
                        .order_by(BackupLog.started_at.desc())
                    )
                    if path:
                        break
            if path is None:
                raise RuntimeError("هنوز نسخه پشتیبانی گرفته نشده است")
        tested = path
        if path.endswith(backup_crypto.SUFFIX):
            folder = _folder(engine, settings)
            name = f"{PREFIX}restoretest_{started.strftime('%Y%m%d_%H%M%S')}.bak"
            plain = _readable(settings, folder, name)
            backup_crypto.decrypt_file(path, plain, _key(settings))
            path = _join(folder, name)
        db = _exec(engine, "SELECT DB_NAME()")[0][0]
        scratch = f"{db}_restore_test"
        files = _exec(engine, "RESTORE FILELISTONLY FROM DISK = ?", path)
        folder = os.path.dirname(path) if "/" in path else path.rsplit("\\", 1)[0]
        moves, params = [], []
        for i, row in enumerate(files):
            logical, kind = row[0], row[2]
            moves.append("MOVE ? TO ?")
            ext = "ldf" if kind == "L" else "mdf" if i == 0 else f"ndf{i}"
            params += [logical, _join(folder, f"{scratch}.{ext}")]
        _exec(
            engine,
            "DECLARE @db sysname = ?; RESTORE DATABASE @db FROM DISK = ? WITH REPLACE, CHECKSUM, "
            + ", ".join(moves),
            scratch,
            path,
            *params,
        )
        _exec(engine, "DECLARE @db sysname = ?; DBCC CHECKDB (@db) WITH NO_INFOMSGS", scratch)
        counts = _exec(
            engine,
            "DECLARE @db sysname = ?, @sql nvarchar(max); "
            "SET @sql = N'SELECT (SELECT COUNT(*) FROM ' + QUOTENAME(@db) + N'.dbo.organization), "
            "(SELECT COUNT(*) FROM ' + QUOTENAME(@db) + N'.dbo.voucher), "
            "(SELECT COUNT(*) FROM ' + QUOTENAME(@db) + N'.dbo.item), "
            "(SELECT TOP 1 version_num FROM ' + QUOTENAME(@db) + N'.dbo.alembic_version)'; "
            "EXEC sp_executesql @sql",
            scratch,
        )[0]
        if counts[0] != 1:
            raise RuntimeError("نسخه بازیابی‌شده اطلاعات سازمان را ندارد")
        result = {
            "path": tested,
            "organizations": counts[0],
            "vouchers": counts[1],
            "items": counts[2],
            "schema": counts[3],
        }
    except Exception as e:
        _log(engine, "restore_test", "failed", started, path=tested, message=_short(e))
        raise
    finally:
        if plain is not None:
            plain.unlink(missing_ok=True)
        if scratch:
            _exec(
                engine,
                "DECLARE @db sysname = ?, @sql nvarchar(max); "
                "IF DB_ID(@db) IS NOT NULL BEGIN "
                "SET @sql = N'ALTER DATABASE ' + QUOTENAME(@db) + "
                "N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE ' + QUOTENAME(@db); "
                "EXEC sp_executesql @sql; END",
                scratch,
            )
    _log(
        engine,
        "restore_test",
        "ok",
        started,
        path=tested,
        verified=True,
        message=f"vouchers={result['vouchers']} items={result['items']} schema={result['schema']}",
    )
    return result


def _short(e: Exception) -> str:
    # Driver messages can be long; keep the useful part, never a connection string.
    return str(e).split("(SQLExecDirectW)")[0][-600:]


# --- status for the dashboard -------------------------------------------------


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def status(s: Session) -> dict[str, Any]:
    org = s.scalar(select(Organization))
    now = utcnow()

    def last(kind: str, ok_only: bool) -> BackupLog | None:
        q = select(BackupLog).where(BackupLog.kind == kind)
        if ok_only:
            q = q.where(BackupLog.status == "ok")
        return s.scalar(q.order_by(BackupLog.started_at.desc()))

    backup, restore, last_any, copy, copy_any = (
        last("backup", True),
        last("restore_test", True),
        last("backup", False),
        last("copy", True),
        last("copy", False),
    )
    offsite = _aware(org.last_offsite_backup_at) if org else None
    days = org.backup_warning_days if org else 3
    warnings: list[str] = []
    if backup is None or (_aware(backup.started_at) or now) < now - timedelta(hours=26):
        warnings.append("در ۲۴ ساعت گذشته نسخه پشتیبان موفق گرفته نشده است")
    if last_any is not None and last_any.status == "failed":
        warnings.append("آخرین تلاش پشتیبان‌گیری ناموفق بود")
    if copy_any is not None and copy_any.status == "failed":
        warnings.append("آخرین کپی رمزنگاری‌شده به مقصد دوم ناموفق بود")
    if offsite is None or offsite < now - timedelta(days=days):
        warnings.append(f"بیش از {days} روز است که نسخه پشتیبان به بیرون از این سیستم کپی نشده است")
    if restore is None or (_aware(restore.started_at) or now) < now - timedelta(days=30):
        warnings.append("در ۳۰ روز گذشته آزمون بازیابی موفق ثبت نشده است")

    def row(b: BackupLog | None) -> dict[str, Any] | None:
        if b is None:
            return None
        return {
            "at": _aware(b.started_at),
            "status": b.status,
            "file_path": b.file_path,
            "size_bytes": b.size_bytes,
            "verified": b.verified,
            "message": b.message,
        }

    return {
        "last_backup": row(backup),
        "last_attempt": row(last_any),
        "last_restore_test": row(restore),
        "last_copy": row(copy),
        "last_offsite_copy_at": offsite,
        "warning_days": days,
        "warnings": warnings,
    }


def mark_offsite(s: Session) -> datetime:
    org = s.scalar(select(Organization).with_for_update())
    assert org is not None
    now = utcnow()
    org.last_offsite_backup_at = now
    return now


def history(s: Session, limit: int = 30) -> list[dict[str, Any]]:
    rows = list(s.scalars(select(BackupLog).order_by(BackupLog.started_at.desc()).limit(limit)))
    out = []
    for b in rows:
        started, finished = _aware(b.started_at), _aware(b.finished_at)
        out.append(
            {
                "kind": b.kind,
                "status": b.status,
                "at": started,
                "seconds": round((finished - started).total_seconds(), 1)
                if started and finished
                else None,
                "file_path": b.file_path,
                "size_bytes": b.size_bytes,
                "message": b.message,
            }
        )
    return out
