"""Installation commands. Passwords are prompted, never passed as arguments or defaults."""

from __future__ import annotations

import click
from flask import Flask
from sqlalchemy import select

from app.core.db import unit_of_work
from app.core.numbering import ensure_counters
from app.core.security import hash_password
from app.modules.accounting.models import FiscalYear
from app.modules.accounting.services.chart import seed_defaults
from app.modules.accounting.services.fiscal import current_jalali_year, ensure_year
from app.modules.audit import service as audit
from app.modules.iam.models import AppUser, Role, UserScope
from app.modules.iam.permissions import ADMIN_ROLE
from app.modules.iam.services.auth import validate_password
from app.modules.iam.services.roles import sync_catalog
from app.modules.inventory.services.catalog import seed_catalog
from app.modules.inventory.services.stock import ensure_default_warehouses
from app.modules.organization.models import Branch
from app.modules.organization.services import ensure_organization


def register_cli(app: Flask) -> None:
    @app.cli.command("sync-permissions")
    def sync_permissions() -> None:
        """Sync the permission catalog and create missing system roles."""
        with unit_of_work() as s:
            sync_catalog(s)
        click.echo("permissions synced")

    def _seed_all() -> bool:
        with unit_of_work() as s:
            sync_catalog(s)
            seeded = seed_defaults(s)
            ensure_year(s, current_jalali_year())
            seed_catalog(s)
            ensure_default_warehouses(s)
            ensure_counters(
                s,
                list(s.scalars(select(FiscalYear.id).where(FiscalYear.status == "open"))),
                list(s.scalars(select(Branch.id))),
            )
        return seeded

    @app.cli.command("seed-defaults")
    def seed_defaults_cmd() -> None:
        """Chart, posting rules, fiscal year, units, price list, warehouses (idempotent)."""
        _seed_all()
        click.echo("defaults ensured")

    @app.cli.command("seed-accounting")
    def seed_accounting() -> None:
        """Alias of seed-defaults (kept for phase 2 instructions)."""
        _seed_all()
        click.echo("defaults ensured")

    @app.cli.command("setup")
    @click.option("--org-name", required=True, help="نام سازمان/فروشگاه")
    @click.option("--branch-code", default="01", show_default=True)
    @click.option("--branch-name", default="شعبه مرکزی", show_default=True)
    @click.option("--admin-username", default="admin", show_default=True)
    @click.option("--admin-full-name", default="مدیر سیستم", show_default=True)
    @click.password_option("--admin-password", prompt="رمز مدیر سیستم")
    def setup(
        org_name: str,
        branch_code: str,
        branch_name: str,
        admin_username: str,
        admin_full_name: str,
        admin_password: str,
    ) -> None:
        """First-time setup: organization, main branch, roles and the administrator.

        Safe to re-run: existing records are kept; an existing admin is not modified.
        """
        validate_password(admin_password, admin_username)
        with unit_of_work() as s:
            ensure_organization(s, org_name)
            sync_catalog(s)
            seed_defaults(s)
            ensure_year(s, current_jalali_year())
            seed_catalog(s)
            code = branch_code.upper()
            if s.scalar(select(Branch).where(Branch.code == code)) is None:
                s.add(Branch(code=code, name=branch_name, is_active=True))
                s.flush()
            ensure_default_warehouses(s)
            ensure_counters(
                s,
                list(s.scalars(select(FiscalYear.id).where(FiscalYear.status == "open"))),
                list(s.scalars(select(Branch.id))),
            )
            if s.scalar(select(AppUser).where(AppUser.username == admin_username)) is not None:
                click.echo(f"user {admin_username!r} already exists; left unchanged")
                return
            admin_role = s.scalar(select(Role).where(Role.code == ADMIN_ROLE))
            assert admin_role is not None
            user = AppUser(
                username=admin_username,
                full_name=admin_full_name,
                password_hash=hash_password(admin_password),
                is_active=True,
                must_change_password=False,
                failed_attempts=0,
            )
            user.roles = [admin_role]
            user.scopes = [UserScope(branch_id=None)]
            s.add(user)
            s.flush()
            audit.record(
                s,
                "setup.completed",
                user_id=user.id,
                entity_type="app_user",
                entity_id=user.id,
                data={"org": org_name, "admin": admin_username},
            )
        click.echo("setup complete")

    @app.cli.command("backup")
    def backup_cmd() -> None:
        """Checksummed backup + RESTORE VERIFYONLY (run daily from Windows Task Scheduler)."""
        from app.modules.system import backup

        result = backup.run_backup(app.extensions["db_engine"], app.config["SETTINGS"])
        click.echo(f"backup ok: {result.path} ({result.size_bytes or '?'} bytes, verified)")
        if result.copy:
            click.echo(
                f"encrypted copy ok: {result.copy.path} ({result.copy.size_bytes} bytes, "
                f"sha256 {result.copy.sha256[:16]}…, decrypted and compared)"
            )

    @app.cli.command("backup-keygen")
    def backup_keygen() -> None:
        """Print a new random backup key (once). Store it in NEXTCAM_BACKUP_KEY AND offline."""
        from app.modules.system.backup_crypto import generate_key

        click.echo(generate_key())
        click.echo(
            "این کلید را در NEXTCAM_BACKUP_KEY و یک جای امن بیرون از سرور نگه دارید؛ "
            "بدون آن نسخه‌های رمزنگاری‌شده قابل بازیابی نیستند.",
            err=True,
        )

    @app.cli.command("backup-restore-test")
    @click.option("--file", "path", default=None, help="فایل پشتیبان؛ پیش‌فرض آخرین نسخه موفق")
    def restore_test_cmd(path: str | None) -> None:
        """Restore a backup under a scratch name, run DBCC CHECKDB, compare, then drop it."""
        from app.modules.system import backup

        result = backup.restore_test(app.extensions["db_engine"], app.config["SETTINGS"], path)
        click.echo(f"restore test ok: {result}")
