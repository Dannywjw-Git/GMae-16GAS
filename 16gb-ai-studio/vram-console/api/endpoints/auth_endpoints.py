#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
认证端点（中间层重构 M3）
- GET  /api/auth/status — 认证状态（公开）
- POST /api/auth/setup — 首次设置管理员（公开）
- POST /api/auth/login — 登录（公开，设置 Session Cookie）
- POST /api/auth/forgot — 忘记密码（公开，发送验证码）
- POST /api/auth/reset — 重置密码（公开，验证码+新密码）
- POST /api/auth/logout — 登出（清除 Session Cookie）
- POST /api/auth/change-password — 修改密码（需认证）
"""
import json
from api.router import router
from api.request import Request
from api.response import Response
from api import auth as auth_mod
from core.response import api_success


@router.get("/api/auth/status")
def get_auth_status(req: Request) -> Response:
    """认证状态（公开）。"""
    return Response.success(auth_mod.auth_status())


@router.post("/api/auth/setup")
def post_auth_setup(req: Request) -> Response:
    """首次设置管理员账户（公开，仅在无管理员时可用）。

    Body 参数：
        email: 管理员邮箱
        password: 密码（至少6位）
    """
    ok, msg = auth_mod.setup_admin(
        req.body_get("email", ""),
        req.body_get("password", "")
    )
    if ok:
        return Response.success({"message": msg})
    return Response.error("BAD_REQUEST", msg, http_status=400)


@router.post("/api/auth/login")
def post_auth_login(req: Request) -> Response:
    """登录（公开，设置 Session Cookie）。

    Body 参数：
        email: 邮箱
        password: 密码
        remember: 是否记住我（30天），默认 false
    """
    ok, user = auth_mod.authenticate(
        req.body_get("email", ""),
        req.body_get("password", "")
    )
    if not ok:
        return Response.error("UNAUTHORIZED", "邮箱或密码不正确", http_status=401)

    session_id = auth_mod.create_session(
        user["email"],
        remember=req.body_get("remember", False)
    )
    max_age = auth_mod.SESSION_REMEMBER_TTL if req.body_get("remember") else auth_mod.SESSION_DEFAULT_TTL
    resp = Response.success({"message": "登录成功", "email": user["email"]})
    resp.headers["Set-Cookie"] = "{}={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(
        auth_mod.SESSION_COOKIE_NAME, session_id, max_age
    )
    return resp


@router.post("/api/auth/forgot")
def post_auth_forgot(req: Request) -> Response:
    """忘记密码（公开，发送验证码到邮箱）。

    Body 参数：
        email: 注册邮箱
    """
    ok, msg = auth_mod.generate_reset_code(req.body_get("email", ""))
    if ok:
        return Response.success({"message": msg})
    return Response.error("BAD_REQUEST", msg, http_status=400)


@router.post("/api/auth/reset")
def post_auth_reset(req: Request) -> Response:
    """重置密码（公开，验证码+新密码）。

    Body 参数：
        email: 注册邮箱
        code: 6位验证码
        password: 新密码（至少6位）
    """
    ok, msg = auth_mod.reset_password(
        req.body_get("email", ""),
        req.body_get("code", ""),
        req.body_get("password", "")
    )
    if ok:
        return Response.success({"message": msg})
    return Response.error("BAD_REQUEST", msg, http_status=400)


@router.post("/api/auth/logout")
def post_auth_logout(req: Request) -> Response:
    """登出（清除 Session Cookie）。"""
    session_id = req.cookie(auth_mod.SESSION_COOKIE_NAME, "")
    auth_mod.destroy_session(session_id)
    resp = Response.success({"message": "已登出"})
    resp.headers["Set-Cookie"] = "{}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0".format(
        auth_mod.SESSION_COOKIE_NAME
    )
    return resp


@router.post("/api/auth/change-password")
def post_auth_change_password(req: Request) -> Response:
    """修改密码（需认证）。

    Body 参数：
        old_password: 旧密码
        new_password: 新密码（至少6位）
    """
    # 获取当前用户（从 Session）
    session_id = req.cookie(auth_mod.SESSION_COOKIE_NAME, "")
    sess = auth_mod.get_session(session_id)
    email = sess.get("user_email") if sess else None

    ok, msg = auth_mod.change_password(
        email or "",
        req.body_get("old_password", ""),
        req.body_get("new_password", "")
    )
    if ok:
        return Response.success({"message": msg})
    return Response.error("BAD_REQUEST", msg, http_status=400)
