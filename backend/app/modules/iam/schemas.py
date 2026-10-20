from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip(v: str) -> str:
    return v.strip()


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class RoleRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    must_change_password: bool
    roles: list[RoleRef]
    permissions: list[str]
    all_branches: bool
    branch_ids: list[uuid.UUID]
    session_expires_at: datetime | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    full_name: str
    is_active: bool
    must_change_password: bool
    is_locked: bool
    last_login_at: datetime | None
    roles: list[RoleRef]
    all_branches: bool
    branch_ids: list[uuid.UUID]
    row_version: str
    created_at: datetime


class UserCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=64, pattern=r"^[\w.\-]+$")
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=1, max_length=256)
    role_ids: list[uuid.UUID] = Field(min_length=1)
    all_branches: bool = False
    branch_ids: list[uuid.UUID] = []
    must_change_password: bool = True


class UserUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    is_active: bool | None = None
    role_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    all_branches: bool | None = None
    branch_ids: list[uuid.UUID] | None = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)


class PermissionOut(BaseModel):
    code: str
    group: str
    label: str


class RoleOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_system: bool
    is_locked: bool
    permissions: list[str]
    user_count: int
    row_version: str


class RoleCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = []

    _upper = field_validator("code", mode="before")(lambda v: str(v).strip().upper())


class RoleUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None


class MobileLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    device_name: str | None = Field(default=None, max_length=100)


class MobileRefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class MobileTokensOut(BaseModel):
    """Bearer tokens for the visitor app (kept in Android Keystore, ADR-0004)."""

    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    user: MeOut
