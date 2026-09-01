# -*- coding: utf-8 -*-
"""
GMae 调度中心认证模块
- 用户管理（单管理员，users.json）
- 密码哈希（PBKDF2-HMAC-SHA256，零依赖）
- Session 管理（Cookie + 内存存储）
- SMTP 邮件发送（QQ 邮箱，SSL 465）
- 密码重置验证码（6位数字，10分钟有效期）
"""

import os
import json
import time
import uuid
import hmac
import hashlib
import secrets
import smtplib
from email.mime.text import MIMEText
from email.header import Header

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")

# Session 配置
SESSION_COOKIE_NAME = "gmae_session"
SESSION_DEFAULT_TTL = 7 * 24 * 3600       # 7 天
SESSION_REMEMBER_TTL = 30 * 24 * 3600      # 30 天（记住我）
SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")
SESSIONS = {}  # session_id -> {user_email, expires_at, created_at, remember}

def _load_sessions() -> None:
    """启动时从 sessions.json 加载持久化 session（重启不丢登录态）。"""
    global SESSIONS
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = int(time.time())
            SESSIONS = {k: v for k, v in data.items() if v.get("expires_at", 0) > now}
            if len(SESSIONS) < len(data):
                _save_sessions()  # 清理过期后回写
    except Exception:
        SESSIONS = {}

def _save_sessions() -> None:
    """持久化 session 到 sessions.json。"""
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(SESSIONS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

_load_sessions()  # 模块加载时恢复 session

# 验证码配置
RESET_CODES = {}  # email -> {code, expires_at, attempts}
RESET_CODE_TTL = 10 * 60  # 10 分钟
RESET_MAX_ATTEMPTS = 5

# SMTP 配置（从环境变量读取，不明文存储）
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
SMTP_USER = os.environ.get("GMAE_SMTP_USER", "dannywxx@qq.com")  # 用户指定官方 SMTP 信箱
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")


# ============================================================
# 密码哈希（PBKDF2-HMAC-SHA256，Python 标准库，零依赖）
# ============================================================

def hash_password(password: str, salt: bytes = None, iterations: int = 100000) -> str:
    """生成密码哈希，返回格式 pbkdf2_sha256$100000$<salt_hex>$<hash_hex>"""
    if salt is None:
        salt = secrets.token_bytes(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(iterations, salt.hex(), dk.hex())


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码是否匹配存储的哈希"""
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_hash = parts[3]
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk.hex(), expected_hash)
    except Exception:
        return False


# ============================================================
# 用户管理（单管理员，users.json）
# ============================================================

def _load_users() -> dict:
    """加载用户数据，失败返回空 dict"""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users(users: dict) -> bool:
    """保存用户数据到 users.json"""
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def has_admin() -> bool:
    """是否已设置管理员账户"""
    users = _load_users()
    return bool(users.get("admin"))


def setup_admin(email: str, password: str) -> tuple:
    """首次设置管理员账户。返回 (ok, message)"""
    if has_admin():
        return False, "管理员账户已存在，如需重置请使用忘记密码"
    if not email or "@" not in email:
        return False, "邮箱格式不正确"
    if not password or len(password) < 6:
        return False, "密码至少 6 位"
    users = _load_users()
    users["admin"] = {
        "email": email.strip().lower(),
        "password_hash": hash_password(password),
        "created_at": int(time.time()),
        "role": "admin",
    }
    if _save_users(users):
        return True, "管理员账户创建成功"
    return False, "保存用户数据失败"


def authenticate(email: str, password: str) -> tuple:
    """验证邮箱+密码，返回 (ok, user_dict)"""
    users = _load_users()
    admin = users.get("admin")
    if not admin:
        return False, None
    if admin.get("email", "").lower() != (email or "").strip().lower():
        return False, None
    if not verify_password(password, admin.get("password_hash", "")):
        return False, None
    return True, admin


def change_password(email: str, old_password: str, new_password: str) -> tuple:
    """修改密码。返回 (ok, message)"""
    ok, user = authenticate(email, old_password)
    if not ok:
        return False, "原密码不正确"
    if not new_password or len(new_password) < 6:
        return False, "新密码至少 6 位"
    users = _load_users()
    if users.get("admin", {}).get("email", "").lower() == email.strip().lower():
        users["admin"]["password_hash"] = hash_password(new_password)
        users["admin"]["updated_at"] = int(time.time())
        if _save_users(users):
            # 清除该用户所有 Session
            _clear_user_sessions(email)
            return True, "密码修改成功"
    return False, "修改密码失败"


def reset_password(email: str, code: str, new_password: str) -> tuple:
    """通过验证码重置密码。返回 (ok, message)"""
    ok, msg = _verify_reset_code(email, code)
    if not ok:
        return False, msg
    if not new_password or len(new_password) < 6:
        return False, "新密码至少 6 位"
    users = _load_users()
    if users.get("admin", {}).get("email", "").lower() == email.strip().lower():
        users["admin"]["password_hash"] = hash_password(new_password)
        users["admin"]["updated_at"] = int(time.time())
        if _save_users(users):
            # 清除该用户所有 Session
            _clear_user_sessions(email)
            # 清除验证码
            RESET_CODES.pop(email.strip().lower(), None)
            return True, "密码重置成功"
    return False, "重置密码失败"


# ============================================================
# Session 管理（Cookie + 内存存储）
# ============================================================

def create_session(email: str, remember: bool = False) -> str:
    """创建 Session，返回 session_id"""
    session_id = secrets.token_urlsafe(32)
    ttl = SESSION_REMEMBER_TTL if remember else SESSION_DEFAULT_TTL
    SESSIONS[session_id] = {
        "user_email": email.strip().lower(),
        "expires_at": int(time.time()) + ttl,
        "created_at": int(time.time()),
        "remember": remember,
    }
    _save_sessions()
    return session_id


def get_session(session_id: str) -> dict:
    """获取 Session，过期返回 None"""
    if not session_id:
        return None
    sess = SESSIONS.get(session_id)
    if not sess:
        return None
    if sess["expires_at"] < int(time.time()):
        SESSIONS.pop(session_id, None)
        return None
    return sess


def destroy_session(session_id: str) -> None:
    """销毁 Session（登出）"""
    SESSIONS.pop(session_id, None)
    _save_sessions()


def _clear_user_sessions(email: str) -> None:
    """清除指定用户的所有 Session（修改密码/重置密码后调用）"""
    email = email.strip().lower()
    expired = [sid for sid, s in SESSIONS.items() if s.get("user_email") == email]
    for sid in expired:
        SESSIONS.pop(sid, None)


def parse_cookie(cookie_header: str) -> dict:
    """解析 Cookie 头，返回 dict"""
    cookies = {}
    if not cookie_header:
        return cookies
    for part in cookie_header.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


# ============================================================
# 密码重置验证码
# ============================================================

def generate_reset_code(email: str) -> tuple:
    """生成密码重置验证码并发送邮件。返回 (ok, message)"""
    email = email.strip().lower()
    # 检查邮箱是否是管理员邮箱
    users = _load_users()
    admin = users.get("admin")
    if not admin or admin.get("email", "").lower() != email:
        # 为安全起见，不暴露邮箱是否存在，统一返回成功
        return True, "如果该邮箱已注册，验证码已发送"
    code = "{:06d}".format(secrets.randbelow(1000000))
    RESET_CODES[email] = {
        "code": code,
        "expires_at": int(time.time()) + RESET_CODE_TTL,
        "attempts": 0,
    }
    ok, msg = _send_reset_email(email, code)
    if ok:
        return True, "验证码已发送到邮箱，有效期 10 分钟"
    return False, "邮件发送失败: " + msg


def _verify_reset_code(email: str, code: str) -> tuple:
    """验证重置验证码。返回 (ok, message)"""
    email = email.strip().lower()
    record = RESET_CODES.get(email)
    if not record:
        return False, "验证码不存在或已过期"
    if record["expires_at"] < int(time.time()):
        RESET_CODES.pop(email, None)
        return False, "验证码已过期"
    record["attempts"] = record.get("attempts", 0) + 1
    if record["attempts"] > RESET_MAX_ATTEMPTS:
        RESET_CODES.pop(email, None)
        return False, "验证次数过多，请重新获取验证码"
    if not hmac.compare_digest(str(record["code"]), str(code).strip()):
        return False, "验证码不正确"
    return True, "验证通过"


# ============================================================
# SMTP 邮件发送（QQ 邮箱，SSL 465）
# ============================================================

def _send_reset_email(to_email: str, code: str) -> tuple:
    """发送密码重置验证码邮件。返回 (ok, message)"""
    if not SMTP_PASSWORD:
        return False, "SMTP 密码未配置（环境变量 SMTP_PASSWORD）"
    subject = "【GMae 调度中心】密码重置验证码"
    body = """
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 40px 20px;">
  <div style="max-width: 480px; margin: 0 auto; background: #fff; border-radius: 12px; padding: 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
    <div style="text-align: center; margin-bottom: 24px;">
      <div style="font-size: 28px; font-weight: 700; color: #0d9488; margin-bottom: 8px;">GMae</div>
      <div style="color: #666; font-size: 14px;">GPU Maestro · 显存指挥家</div>
    </div>
    <h2 style="color: #1a1a1a; font-size: 18px; margin: 0 0 16px 0;">密码重置验证码</h2>
    <p style="color: #444; font-size: 14px; line-height: 1.6; margin: 0 0 24px 0;">
      您正在重置 GMae 调度中心的登录密码。请在页面中输入以下验证码完成验证：
    </p>
    <div style="background: #f0fdfa; border: 1px solid #99f6e4; border-radius: 8px; padding: 20px; text-align: center; margin-bottom: 24px;">
      <div style="font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #0d9488; font-family: 'Courier New', monospace;">{code}</div>
    </div>
    <p style="color: #888; font-size: 12px; line-height: 1.6; margin: 0;">
      验证码有效期为 10 分钟，请勿泄露给他人。<br>
      如果不是您本人操作，请忽略此邮件。
    </p>
    <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #eee; text-align: center;">
      <span style="color: #aaa; font-size: 11px;">GMae Prism Engine · 消费级 AI 服务器显存编排专家</span>
    </div>
  </div>
</body>
</html>
""".format(code=code)
    try:
        msg = MIMEText(body, "html", "utf-8")
        msg["From"] = Header("GMae 调度中心 <{}>".format(SMTP_USER), "utf-8")
        msg["To"] = to_email
        msg["Subject"] = Header(subject, "utf-8")
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to_email], msg.as_string())
        return True, "邮件发送成功"
    except Exception as e:
        return False, str(e)


# ============================================================
# 认证状态查询
# ============================================================

def auth_status() -> dict:
    """返回认证系统状态"""
    return {
        "ok": True,
        "has_admin": has_admin(),
        "admin_email": (_load_users().get("admin") or {}).get("email", ""),
        "smtp_configured": bool(SMTP_PASSWORD),
        "smtp_user": SMTP_USER,
        "active_sessions": len(SESSIONS),
    }
