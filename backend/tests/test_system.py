from __future__ import annotations

import pytest
from flask.testing import FlaskClient
from pydantic import ValidationError

from app import create_app
from app.core.config import Settings
from tests.conftest import UNREACHABLE_URL


def test_health(client: FlaskClient) -> None:
    resp = client.get("/api/v1/system/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_ready_reports_unreachable_database() -> None:
    app = create_app(
        Settings(env="test", database_url=UNREACHABLE_URL, secret_key="x")  # type: ignore[arg-type]
    )
    resp = app.test_client().get("/api/v1/system/ready")
    assert resp.status_code == 503
    assert resp.get_json()["database"] == "down"


@pytest.mark.db
def test_ready_with_database(client: FlaskClient, db_url: str) -> None:
    resp = client.get("/api/v1/system/ready")
    assert resp.status_code == 200
    assert resp.get_json()["database"] == "up"


def test_unknown_route_returns_structured_error(client: FlaskClient) -> None:
    resp = client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_unhandled_error_hides_internals(client: FlaskClient) -> None:
    app = client.application

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    resp = app.test_client().get("/boom")
    body = resp.get_json()
    assert resp.status_code == 500
    assert "secret" not in str(body)
    assert body["error"]["code"] == "internal_error"


def test_rejects_non_sqlserver_database() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", database_url="sqlite:///x.db", secret_key="x")  # type: ignore[arg-type]


def test_mock_terminal_forbidden_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[arg-type]
            env="production",
            database_url=UNREACHABLE_URL,
            secret_key="x",
            enable_mock_payment_terminal=True,
        )
