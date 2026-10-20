"""Safe upgrade of a customer installation (phase 10, docs/install/upgrade.md).

``flask upgrade`` after the new release's files are in place:

1. refuse while the program is still in use (a session or register seen in the last
   minutes) — the Windows script stops the server first; registers with the Device
   Agent keep selling offline meanwhile (ADR-0017);
2. a verified backup (and its encrypted copy, if configured) BEFORE touching the schema;
3. all pending migrations in ONE transaction: SQL Server DDL is transactional, so a
   failure leaves the database exactly as it was (the old release still runs on it);
4. permissions and defaults brought up to date (idempotent);
5. integrity checks: schema at head, one organization, every final voucher balanced,
   stock balances equal to the ledger.

The integrity checks also run on their own: ``flask check-integrity``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from flask import Flask
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.audit import service as audit
from app.modules.devices.models import Device
from app.modules.iam.models import MobileSession, UserSession
from app.version import RELEASED, VERSION

BACKEND = Path(__file__).resolve().parents[3]
MIGRATIONS = BACKEND / "migrations"
ACTIVE_MINUTES = 3


class UpgradeError(Exception):
    """Stops the upgrade before anything changed; the message is for the operator."""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    from_revision: str | None
    to_revision: str | None
    backup: str | None = None
    copy: str | None = None
    migrated: bool = False
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def alembic_config(engine: Engine) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["database_url"] = engine.url.render_as_string(hide_password=False)
    return cfg


def revisions(engine: Engine) -> tuple[str | None, str | None]:
    """(current revision of the database, head of this release)."""
    logging.getLogger("alembic").setLevel(logging.WARNING)
    head = ScriptDirectory.from_config(alembic_config(engine)).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current, head


def recent_activity(s: Session, minutes: int = ACTIVE_MINUTES) -> dict[str, int]:
    since = utcnow() - timedelta(minutes=minutes)

    def count(model: Any, *where: Any) -> int:
        return int(s.scalar(select(func.count()).select_from(model).where(*where)) or 0)

    return {
        "sessions": count(
            UserSession, UserSession.revoked_at.is_(None), UserSession.last_seen_at >= since
        ),
        "app": count(
            MobileSession, MobileSession.revoked_at.is_(None), MobileSession.last_seen_at >= since
        ),
        "registers": count(Device, Device.last_seen_at >= since),
    }


def integrity_checks(engine: Engine, *, fresh: bool = False) -> list[Check]:
    current, head = revisions(engine)
    checks = [Check("schema", current == head, f"{current} (head {head})")]
    with Session(engine) as s:
        orgs = int(s.scalar(text("SELECT COUNT(*) FROM organization")) or 0)
        if fresh and orgs == 0:
            checks.append(Check("organization", True, "not set up yet: run flask setup"))
        else:
            checks.append(Check("organization", orgs == 1, f"{orgs} row(s)"))
        unbalanced = int(
            s.scalar(
                text(
                    "SELECT COUNT(*) FROM (SELECT v.id FROM voucher v "
                    "JOIN voucher_line l ON l.voucher_id = v.id WHERE v.status = 'final' "
                    "GROUP BY v.id HAVING SUM(l.debit) <> SUM(l.credit)) x"
                )
            )
            or 0
        )
        checks.append(Check("vouchers balanced", unbalanced == 0, f"{unbalanced} unbalanced"))
        # The newest ledger row per item/warehouse carries the running balance.
        drift = int(
            s.scalar(
                text(
                    "SELECT COUNT(*) FROM stock_balance b OUTER APPLY ("
                    " SELECT TOP 1 l.balance_qty, l.balance_value FROM stock_ledger l"
                    " WHERE l.item_id = b.item_id AND l.warehouse_id = b.warehouse_id"
                    " ORDER BY l.seq DESC) last "
                    "WHERE b.qty <> COALESCE(last.balance_qty, 0) "
                    "OR b.value <> COALESCE(last.balance_value, 0)"
                )
            )
            or 0
        )
        checks.append(Check("stock = ledger", drift == 0, f"{drift} item/warehouse mismatches"))
    return checks


def _support_note(engine: Engine) -> str | None:
    from app.modules.system import license

    with Session(engine) as s:
        try:
            p = license.active(s)
        except Exception:  # noqa: BLE001 - before 0015 the license table may not exist
            return None
    if p is not None and p.support_until is not None and p.support_until < RELEASED:
        return (
            f"پشتیبانی مجوز تا {p.support_until.isoformat()} است و این نسخه "
            f"({VERSION}) بعد از آن منتشر شده؛ برای تمدید با فروشنده تماس بگیرید"
        )
    return None


def run(
    app: Flask,
    *,
    skip_backup: bool = False,
    force: bool = False,
    echo: Callable[[str], None] = print,
) -> Report:
    from app.cli import seed_all
    from app.modules.system import backup

    engine: Engine = app.extensions["db_engine"]
    settings = app.config["SETTINGS"]
    current, head = revisions(engine)
    report = Report(current, head)
    echo(f"NEXTCAM {VERSION}: database at {current or 'empty'}, release head {head}")
    note = _support_note(engine)
    if note:
        echo("warning: " + note)

    if current != head and current is not None:
        with Session(engine) as s:
            busy = recent_activity(s)
        if any(busy.values()) and not force:
            raise UpgradeError(
                "برنامه هنوز در حال استفاده است "
                f"(نشست وب {busy['sessions']}، اپ {busy['app']}، صندوق {busy['registers']} "
                f"در {ACTIVE_MINUTES} دقیقه‌ی اخیر). سرویس NEXTCAM را متوقف کنید و چند دقیقه "
                "بعد دوباره اجرا کنید (یا --force)."
            )
        if skip_backup:
            echo("warning: backup skipped (--skip-backup)")
        else:
            echo("backup before upgrade …")
            try:
                result = backup.run_backup(engine, settings)
            except Exception as e:
                raise UpgradeError(
                    "پشتیبان پیش از به‌روزرسانی ناموفق بود؛ دیتابیس تغییری نکرده است: "
                    + backup._short(e)
                ) from e
            report.backup = result.path
            report.copy = result.copy.path if result.copy else None
            echo(f"backup ok: {result.path}" + (f" + {report.copy}" if report.copy else ""))
        echo(f"migrating {current} → {head} (one transaction) …")
        try:
            command.upgrade(alembic_config(engine), "head")
        except Exception as e:
            raise UpgradeError(
                "به‌روزرسانی دیتابیس ناموفق بود و کامل برگشت داده شد؛ نسخه‌ی قبلی برنامه "
                f"روی همین دیتابیس کار می‌کند. پشتیبان: {report.backup or '-'}. خطا: "
                + backup._short(e)
            ) from e
        report.migrated = True
    elif current is None:
        echo("empty database: creating the schema …")
        command.upgrade(alembic_config(engine), "head")
        report.migrated = True
    else:
        echo("schema already up to date")

    with app.app_context():
        seed_all()
    report.to_revision = revisions(engine)[0]
    report.checks = integrity_checks(engine, fresh=current is None)
    with Session(engine) as s, s.begin():
        has_org = s.scalar(text("SELECT COUNT(*) FROM organization"))
        if has_org:
            audit.record(
                s,
                "system.upgraded",
                user_id=None,
                data={
                    "version": VERSION,
                    "from": report.from_revision,
                    "to": report.to_revision,
                    "backup": report.backup,
                    "checks_ok": report.ok,
                },
            )
    return report
