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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
