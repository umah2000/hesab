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

    # SEP central PC-POS (ADR-0024): addresses and credentials issued by Saman. The
    # service and its identity server may listen on different ports.
    sep_pcpos_url: str | None = None  # e.g. https://<server>:<service port>
    sep_pcpos_identity_url: str | None = None  # e.g. https://<server>:<identity port>
    sep_pcpos_client_id: str | None = None
    sep_pcpos_client_secret: SecretStr | None = None
    sep_pcpos_username: str | None = None
    sep_pcpos_password: SecretStr | None = None
    # Saman's first phase is plain http inside its network; anything else needs TLS.
    sep_pcpos_allow_http: bool = False
    # How long to wait for the device's answer (the customer swipes and types the PIN).
    sep_pcpos_timeout_seconds: int = 100

    # Weighbridge platform (VA) → accounting (ADR-0025). Both set = the webhook is on.
    va_webhook_secret: SecretStr | None = None
    va_tenant_id: str | None = None  # the VA organisation whose statements are posted here
    va_branch_code: str | None = None  # NEXTCAM branch of its vouchers; empty = none

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
    # Where this program reads that folder, if not under the same path (SQL Server on
    # another machine: a share; empty = backup_dir).
    backup_read_dir: str | None = None
    # Phase 10: every backup is also encrypted (AES-256-GCM, this key) and copied to a
    # second destination: USB disk, NAS share or a cloud-synced folder. Never plaintext.
    backup_key: SecretStr | None = None
    backup_copy_dir: str | None = None
    backup_copy_keep: int = 30

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

    @field_validator("sep_pcpos_url", "sep_pcpos_identity_url")
    @classmethod
    def _sep_url(cls, v: str | None, info: ValidationInfo) -> str | None:
        if not v:
            return None
        if not v.startswith(("https://", "http://")):
            raise ValueError(f"{info.field_name} must start with https://")
        return v.rstrip("/")

    @field_validator("backup_copy_dir")
    @classmethod
    def _copies_are_encrypted(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v and info.data.get("backup_key") is None:
            raise ValueError("backup_copy_dir needs backup_key: copies leave the server encrypted")
        return v

    @field_validator("backup_key")
    @classmethod
    def _valid_backup_key(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None:
            from app.modules.system.backup_crypto import BackupCryptoError, parse_key

            try:
                parse_key(v.get_secret_value())
            except BackupCryptoError as e:
                raise ValueError("backup_key must be 32 bytes in URL-safe base64") from e
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
