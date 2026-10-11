"""Auth, users and roles endpoints. Thin: parse → service → serialize."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, Response, current_app, request
from flask.typing import ResponseReturnValue

from app.core.config import Settings
from app.core.db import new_session, unit_of_work
from app.core.errors import NotFoundError
from app.core.http import PageQuery, if_match, parse_body, parse_query, parse_uuid, to_json
from app.core.idempotency import idempotent
from app.core.openapi import doc
from app.core.ratelimit import limiter
from app.modules.iam.guard import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    current_actor,
    login_required,
    require,
)
from app.modules.iam.models import AppUser, UserSession
from app.modules.iam.schemas import (
    ChangePasswordIn,
    LoginIn,
    MeOut,
    PermissionOut,
    ResetPasswordIn,
    RoleCreateIn,
    RoleOut,
    RoleRef,
    RoleUpdateIn,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from app.modules.iam.services import auth, roles, users

auth_bp = Blueprint("auth", __name__)
users_bp = Blueprint("users", __name__)
roles_bp = Blueprint("roles", __name__)


def _settings() -> Settings:
    settings: Settings = current_app.config["SETTINGS"]
    return settings


def _me(user: AppUser, expires_at: datetime | None = None) -> MeOut:
    actor = auth.actor_for(user, user.id)
    return MeOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        must_change_password=user.must_change_password,
        roles=[RoleRef(id=r.id, code=r.code, name=r.name) for r in user.roles],
        permissions=sorted(actor.permissions),
        all_branches=actor.branch_ids is None,
        branch_ids=sorted(actor.branch_ids or []),
        session_expires_at=expires_at,
    )


def _set_cookies(resp: Response, session_token: str, csrf_token: str, expires: datetime) -> None:
    secure = _settings().cookie_secure
    resp.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=secure,
        samesite="Lax",
        path="/",
        expires=expires,
    )
    # Readable by the SPA so it can echo it in X-CSRF-Token (double submit).
    resp.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="Lax",
        path="/",
        expires=expires,
    )


@auth_bp.post("/login")
@limiter.limit(lambda: _settings().login_rate_limit)
@doc("ورود و ایجاد نشست", body=LoginIn, response=MeOut)
def login() -> ResponseReturnValue:
    data = parse_body(LoginIn)
    result = auth.login(
        data.username,
        data.password,
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    s = new_session()
    try:
        user = s.get(AppUser, result.user_id)
        assert user is not None
        resp = to_json(_me(user, result.expires_at))
    finally:
        s.close()
    _set_cookies(resp, result.session_token, result.csrf_token, result.expires_at)
    return resp


@auth_bp.post("/logout")
@login_required
@doc("خروج و ابطال نشست")
def logout() -> ResponseReturnValue:
    auth.logout(current_actor())
    resp = to_json({"status": "ok"})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    resp.delete_cookie(CSRF_COOKIE, path="/")
    return resp


@auth_bp.get("/me")
@login_required
@doc("کاربر جاری، مجوزها و محدوده دسترسی", response=MeOut)
def me() -> ResponseReturnValue:
    actor = current_actor()
    s = new_session()
    try:
        user = s.get(AppUser, actor.user_id)
        sess = s.get(UserSession, actor.session_id)
        if user is None:
            raise NotFoundError("کاربر یافت نشد")
        return to_json(_me(user, sess.expires_at if sess else None))
    finally:
        s.close()


@auth_bp.post("/change-password")
@login_required
@doc("تغییر رمز عبور کاربر جاری", body=ChangePasswordIn)
def change_password() -> ResponseReturnValue:
    data = parse_body(ChangePasswordIn)
    auth.change_password(current_actor(), data.current_password, data.new_password)
    return to_json({"status": "ok"})


# --- users ------------------------------------------------------------------


@users_bp.get("")
@require("users.manage")
@doc("فهرست کاربران", query=PageQuery, response=UserOut)
def list_users() -> ResponseReturnValue:
    q = parse_query(PageQuery)
    s = new_session()
    try:
        return to_json(users.list_users(s, q))
    finally:
        s.close()


@users_bp.post("")
@require("users.manage")
@doc("ایجاد کاربر", body=UserCreateIn, response=UserOut, idempotent=True)
def create_user() -> ResponseReturnValue:
    data = parse_body(UserCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: users.create_user(s, actor, data))


@users_bp.get("/<user_id>")
@require("users.manage")
@doc("جزئیات کاربر", response=UserOut)
def get_user(user_id: str) -> ResponseReturnValue:
    s = new_session()
    try:
        return to_json(users.get_user(s, parse_uuid(user_id)))
    finally:
        s.close()


@users_bp.patch("/<user_id>")
@require("users.manage")
@doc("ویرایش کاربر (نقش، شعبه، فعال/غیرفعال)", body=UserUpdateIn, response=UserOut, versioned=True)
def update_user(user_id: str) -> ResponseReturnValue:
    data = parse_body(UserUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(users.update_user(s, current_actor(), parse_uuid(user_id), data, version))


@users_bp.post("/<user_id>/reset-password")
@require("users.manage")
@doc("تعیین رمز جدید (کاربر باید در ورود بعدی تغییر دهد)", body=ResetPasswordIn)
def reset_password(user_id: str) -> ResponseReturnValue:
    data = parse_body(ResetPasswordIn)
    with unit_of_work() as s:
        users.reset_password(s, current_actor(), parse_uuid(user_id), data.new_password)
    return to_json({"status": "ok"})


@users_bp.post("/<user_id>/unlock")
@require("users.manage")
@doc("رفع قفل حساب", response=UserOut)
def unlock(user_id: str) -> ResponseReturnValue:
    with unit_of_work() as s:
        return to_json(users.unlock(s, current_actor(), parse_uuid(user_id)))


# --- roles ------------------------------------------------------------------


@roles_bp.get("/permissions")
@require("roles.manage")
@doc("فهرست مجوزها", response=[PermissionOut])
def list_permissions() -> ResponseReturnValue:
    return to_json(list(roles.list_permissions()))


@roles_bp.get("")
@login_required
@doc("فهرست نقش‌ها", response=[RoleOut])
def list_roles() -> ResponseReturnValue:
    actor = current_actor()
    if not (actor.has("roles.manage") or actor.has("users.manage")):
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("شما مجوز این عملیات را ندارید")
    s = new_session()
    try:
        return to_json(list(roles.list_roles(s)))
    finally:
        s.close()


@roles_bp.post("")
@require("roles.manage")
@doc("ایجاد نقش", body=RoleCreateIn, response=RoleOut, idempotent=True)
def create_role() -> ResponseReturnValue:
    data = parse_body(RoleCreateIn)
    actor = current_actor()
    with unit_of_work() as s:
        return idempotent(s, actor.user_id, lambda: roles.create_role(s, actor, data))


@roles_bp.patch("/<role_id>")
@require("roles.manage")
@doc("ویرایش نقش و مجوزها", body=RoleUpdateIn, response=RoleOut, versioned=True)
def update_role(role_id: str) -> ResponseReturnValue:
    data = parse_body(RoleUpdateIn)
    version = if_match()
    with unit_of_work() as s:
        return to_json(roles.update_role(s, current_actor(), parse_uuid(role_id), data, version))
