"""Settings are read only from environment variables (or a local, git-ignored .env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXTCAM_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    secret_key: SecretStr
    log_level: str = "INFO"
    # Mock payment terminal may never be enabled in production (see ADR-0008).
    enable_mock_payment_terminal: bool = False

    # Production server (python -m app.serve). static_dir = built frontend (frontend/dist),
    # so the shop LAN needs only this one service on one port.
    host: str = "0.0.0.0"  # noqa: S104 - a LAN server by design; firewall per install guide
    port: int = 8080
    threads: int = 16
    static_dir: str | None = None
    # HTTPS (phase 10): TLS ends at a reverse proxy on the same machine (deploy/https).
    # Set to the proxy's address (usually 127.0.0.1) so client IPs and the https scheme
    # come from its X-Forwarded-* headers; such headers from anyone else are dropped.
    trusted_proxy: str | None = None

    # Backups (phase 4, risk R2). A folder on the SQL Server machine; empty = SQL Server's
    # default backup folder. Keep this many recent files when the folder is local.
    backup_dir: str | None = None
    backup_keep: int = 14

    # Sessions (ADR-0004). Secure cookies require HTTPS; disable only on a trusted LAN.
    cookie_secure: bool = True
    session_idle_minutes: int = 120
    session_absolute_hours: int = 12
    login_rate_limit: str = "10 per minute"
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    @field_validator("database_url")
    @classmethod
    def _require_mssql(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value().startswith("mssql+pyodbc://"):
            raise ValueError("central database must be SQL Server (mssql+pyodbc://...)")
        return v

    @field_validator("enable_mock_payment_terminal")
    @classmethod
    def _no_mock_in_production(cls, v: bool, info: ValidationInfo) -> bool:
        if v and info.data.get("env") == "production":
            raise ValueError("mock payment terminal cannot be enabled in production")
        return v

    @field_validator("secret_key")
    @classmethod
    def _strong_secret_in_production(cls, v: SecretStr, info: ValidationInfo) -> SecretStr:
        if info.data.get("env") == "production" and len(v.get_secret_value()) < 32:
            raise ValueError("secret_key must be at least 32 characters in production")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
