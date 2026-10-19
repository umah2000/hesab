from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import create_engine, text
from werkzeug.test import TestResponse

from app import create_app
from app.core import refcache
from app.core.config import Settings
from app.core.db import unit_of_work
from app.core.ratelimit import limiter
from app.core.security import hash_password
from app.modules.iam.guard import CSRF_COOKIE, CSRF_HEADER
from app.modules.iam.models import AppUser, Role, UserScope
from app.modules.iam.services.auth import forget_sessions
from app.modules.iam.services.roles import sync_catalog
from app.modules.organization.models import Branch
from app.modules.organization.services import ensure_organization

# Points at a throwaway SQL Server database. Never a production database.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
UNREACHABLE_URL = (
    "mssql+pyodbc://nobody:nothing@127.0.0.1:1/none"
    "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Connection+Timeout=1"
)
BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "Test-Passw0rd"

# Child tables first. audit_event needs its append-only trigger lifted for cleanup.
_TABLES = [
    "visit",
    "sales_order_line",
    "sales_order",
    "visitor_customer",
    "visitor",
    "mobile_token",
    "mobile_session",
    "sync_operation",
    "saved_report_filter",
    "device_job",
    "device",
    "bank_statement_line",
    "cheque_event",
    "treasury_line",
    "cheque",
    "treasury_document",
    "money_account",
    "purchase_charge",
    "purchase_invoice_line",
    "purchase_invoice",
    "purchase_order_line",
    "purchase_order",
    "sales_payment",
    "sales_invoice_line",
    "sales_invoice",
    "terminal_transaction",
    "sales_approval",
    "promotion",
    "cash_shift",
    "backup_log",
    "stock_ledger",
    "stock_balance",
    "stock_document_line",
    "stock_document",
    "item_price",
    "item_barcode",
    "item_unit",
    "item",
    "item_group",
    "scale_barcode_rule",
    "price_list",
    "unit",
    "warehouse",
    "voucher_line",
    "voucher",
    "posting_rule",
    "number_sequence",
    "fiscal_period",
    "fiscal_year",
    "party_note",
    "party",
    "party_group",
    "detail_account",
    "account",
    "idempotency_record",
    "user_session",
    "user_scope",
    "user_role",
    "role_permission",
    "app_user",
    "role",
    "permission",
    "cash_register",
    "branch",
    "organization",
]


def _settings(url: str, **kw: Any) -> Settings:
    return Settings(
        env="test",
        database_url=url,
        secret_key="test-secret",  # type: ignore[arg-type]
        cookie_secure=False,
        **kw,
    )


@pytest.fixture(scope="session")
def migrated_db() -> str | None:
    if not TEST_DATABASE_URL:
        return None
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")
    return TEST_DATABASE_URL


def _wipe(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as conn:
        exists = conn.scalar(text("SELECT OBJECT_ID('audit_event')"))
        if exists is None:
            return
        guarded = [("trg_audit_event_append_only", "audit_event")]
        if conn.scalar(text("SELECT OBJECT_ID('voucher')")) is not None:
            guarded += [
                ("trg_voucher_guard", "voucher"),
                ("trg_voucher_line_guard", "voucher_line"),
            ]
        if conn.scalar(text("SELECT OBJECT_ID('stock_ledger')")) is not None:
            guarded.append(("trg_stock_ledger_append_only", "stock_ledger"))
        if conn.scalar(text("SELECT OBJECT_ID('sales_invoice')")) is not None:
            guarded += [
                ("trg_sales_invoice_guard", "sales_invoice"),
                ("trg_sales_invoice_line_guard", "sales_invoice_line"),
                ("trg_sales_payment_guard", "sales_payment"),
            ]
        if conn.scalar(text("SELECT OBJECT_ID('treasury_document')")) is not None:
            guarded += [
                ("trg_treasury_document_guard", "treasury_document"),
                ("trg_treasury_line_guard", "treasury_line"),
                ("trg_cheque_guard", "cheque"),
                ("trg_cheque_event_append_only", "cheque_event"),
            ]
        if conn.scalar(text("SELECT OBJECT_ID('purchase_invoice')")) is not None:
            guarded += [
                ("trg_purchase_invoice_guard", "purchase_invoice"),
                ("trg_purchase_invoice_line_guard", "purchase_invoice_line"),
                ("trg_purchase_charge_guard", "purchase_charge"),
            ]
        for trg, tbl in guarded:
            conn.execute(text(f"DISABLE TRIGGER {trg} ON {tbl}"))
        conn.execute(text("DELETE FROM audit_event"))
        for t in _TABLES:
            if conn.scalar(text(f"SELECT OBJECT_ID('{t}')")) is not None:
                conn.execute(text(f"DELETE FROM {t}"))  # noqa: S608 - fixed table list
        for trg, tbl in guarded:
            conn.execute(text(f"ENABLE TRIGGER {trg} ON {tbl}"))
    engine.dispose()


@pytest.fixture
def app(migrated_db: str | None) -> Iterator[Flask]:
    if migrated_db:
        _wipe(migrated_db)
    # Process-wide caches must not carry rows from a wiped database into the next test.
    refcache.clear()
    forget_sessions()
    flask_app = create_app(_settings(migrated_db or UNREACHABLE_URL))
    flask_app.config["RATELIMIT_ENABLED"] = False
    limiter.enabled = False
    yield flask_app
    limiter.enabled = True


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def db_url(migrated_db: str | None) -> Iterator[str]:
    if not migrated_db:
        pytest.skip("TEST_DATABASE_URL not set")
    yield migrated_db


@dataclass
class Seed:
    branch_a: uuid.UUID
    branch_b: uuid.UUID
    admin_id: uuid.UUID


def make_user(
    app: Flask,
    username: str,
    role_codes: list[str],
    branch_ids: list[uuid.UUID] | None = None,
    *,
    active: bool = True,
) -> uuid.UUID:
    """branch_ids=None gives access to all branches."""
    with app.app_context(), unit_of_work() as s:
        from sqlalchemy import select

        roles = list(s.scalars(select(Role).where(Role.code.in_(role_codes))))
        assert len(roles) == len(set(role_codes)), role_codes
        u = AppUser(
            username=username,
            full_name=f"کاربر {username}",
            password_hash=hash_password(PASSWORD),
            is_active=active,
            must_change_password=False,
            failed_attempts=0,
        )
        u.roles = roles
        u.scopes = (
            [UserScope(branch_id=None)]
            if branch_ids is None
            else [UserScope(branch_id=b) for b in branch_ids]
        )
        s.add(u)
        s.flush()
        return u.id


def make_role(app: Flask, code: str, permissions: list[str]) -> None:
    with app.app_context(), unit_of_work() as s:
        from sqlalchemy import select

        from app.modules.iam.models import Permission

        perms = list(s.scalars(select(Permission).where(Permission.code.in_(permissions))))
        s.add(Role(code=code, name=code, is_system=False, permissions=perms))


@pytest.fixture
def seed(app: Flask, db_url: str) -> Seed:
    with app.app_context(), unit_of_work() as s:
        ensure_organization(s, "سوپرمارکت آزمایشی")
        sync_catalog(s)
        a = Branch(code="01", name="شعبه یک", is_active=True)
        b = Branch(code="02", name="شعبه دو", is_active=True)
        s.add_all([a, b])
        s.flush()
        branch_a, branch_b = a.id, b.id
    admin_id = make_user(app, "admin", ["ADM"])
    return Seed(branch_a=branch_a, branch_b=branch_b, admin_id=admin_id)


class Api:
    """Test client wrapper that logs in and sends the CSRF header like the SPA does."""

    def __init__(self, client: FlaskClient) -> None:
        self.c = client

    def login(self, username: str, password: str = PASSWORD) -> TestResponse:
        return self.c.post("/api/v1/auth/login", json={"username": username, "password": password})

    def _csrf(self) -> dict[str, str]:
        cookie = self.c.get_cookie(CSRF_COOKIE)
        return {CSRF_HEADER: cookie.value} if cookie else {}

    def get(self, path: str, **kw: Any) -> TestResponse:
        return self.c.get(path, **kw)

    def send(
        self, method: str, path: str, json: Any = None, headers: dict[str, str] | None = None
    ) -> TestResponse:
        return self.c.open(
            path, method=method, json=json, headers={**self._csrf(), **(headers or {})}
        )

    def post(
        self,
        path: str,
        json: Any = None,
        *,
        idem: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> TestResponse:
        h = dict(headers or {})
        if idem is not None:
            h["Idempotency-Key"] = idem
        return self.send("POST", path, json, h)

    def patch(self, path: str, json: Any, version: str | None) -> TestResponse:
        return self.send("PATCH", path, json, {"If-Match": version} if version else {})

    def put(self, path: str, json: Any, version: str | None) -> TestResponse:
        return self.send("PUT", path, json, {"If-Match": version} if version else {})


@pytest.fixture
def api(client: FlaskClient) -> Api:
    return Api(client)


@pytest.fixture
def admin(app: Flask, seed: Seed) -> Api:
    a = Api(app.test_client())
    assert a.login("admin").status_code == 200
    return a


def new_key() -> str:
    return str(uuid.uuid4())
