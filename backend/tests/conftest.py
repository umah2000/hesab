from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.core.config import Settings

# Points at a throwaway SQL Server database. Never a production database.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
UNREACHABLE_URL = (
    "mssql+pyodbc://nobody:nothing@127.0.0.1:1/none"
    "?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Connection+Timeout=1"
)


def _settings(url: str) -> Settings:
    return Settings(env="test", database_url=url, secret_key="test-secret")  # type: ignore[arg-type]


@pytest.fixture
def app() -> Flask:
    return create_app(_settings(TEST_DATABASE_URL or UNREACHABLE_URL))


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def db_url() -> Iterator[str]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    yield TEST_DATABASE_URL
