from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Unicode,
    UniqueConstraint,
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import ActorMixin, Base, EntityMixin, VersionedMixin

user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", UNIQUEIDENTIFIER, ForeignKey("app_user.id"), primary_key=True),
    Column("role_id", UNIQUEIDENTIFIER, ForeignKey("role.id"), primary_key=True),
)

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", UNIQUEIDENTIFIER, ForeignKey("role.id"), primary_key=True),
    Column("permission_code", String(64), ForeignKey("permission.code"), primary_key=True),
)


class Permission(Base):
    """Catalog table synced from ``permissions.CATALOG``; natural key by design."""

    __tablename__ = "permission"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_name: Mapped[str] = mapped_column(Unicode(64))
    label: Mapped[str] = mapped_column(Unicode(128))


class Role(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "role"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(Unicode(100))
    description: Mapped[str | None] = mapped_column(Unicode(500))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    permissions: Mapped[list[Permission]] = relationship(secondary=role_permission, lazy="selectin")


class AppUser(EntityMixin, ActorMixin, VersionedMixin, Base):
    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(Unicode(64), unique=True)
    full_name: Mapped[str] = mapped_column(Unicode(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[Role]] = relationship(secondary=user_role, lazy="selectin")
    scopes: Mapped[list[UserScope]] = relationship(
        back_populates="user", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def permission_codes(self) -> frozenset[str]:
        return frozenset(p.code for r in self.roles for p in r.permissions)


class UserScope(EntityMixin, Base):
    """Branch a user may act in. ``branch_id IS NULL`` means all branches."""

    __tablename__ = "user_scope"
    __table_args__ = (UniqueConstraint("user_id", "branch_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branch.id"))

    user: Mapped[AppUser] = relationship(back_populates="scopes")


class UserSession(EntityMixin, Base):
    __tablename__ = "user_session"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Unicode(300))

    user: Mapped[AppUser] = relationship(lazy="joined")


class MobileSession(EntityMixin, Base):
    """A phone signed in with the visitor app (ADR-0004, ADR-0018).

    Bearer tokens instead of cookies: a short access token and a refresh token that is
    replaced on every use. Presenting a refresh token that was already used revokes the
    whole session (it was copied).
    """

    __tablename__ = "mobile_session"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    device_name: Mapped[str | None] = mapped_column(Unicode(100))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The refresh chain cannot outlive this, however often it is renewed.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(32))


class MobileToken(EntityMixin, Base):
    """Access and refresh tokens of a mobile session, stored only as SHA-256 hashes."""

    __tablename__ = "mobile_token"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mobile_session.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # access | refresh
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # A refresh token is used once; a second use means it was stolen.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
