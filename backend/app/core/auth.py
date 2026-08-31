"""登录鉴权核心：密码哈希、会话令牌、登录限流。

安全设计：
- 密码用 hashlib.scrypt（带每用户随机盐）哈希存储，绝不存明文
- 会话令牌为 32 字节随机值，只写入浏览器 HttpOnly Cookie；数据库仅存其 SHA-256 哈希
  （即使数据库泄露，也无法反推有效 Cookie）
- 登录接口限流：按用户名 5 次 / 10 分钟、按 IP 20 次 / 分钟，防暴力破解
- 校验用常量时间比较，避免时序侧信道
"""

import hashlib
import hmac
import logging
import secrets
import threading
import time
from datetime import timedelta

from fastapi import Request

from app.core.config import now
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

SESSION_COOKIE = "punchcard_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600  # 30 天

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

_LOGIN_USER_MAX = 5
_LOGIN_USER_WINDOW = 600  # 秒
_LOGIN_IP_MAX = 20
_LOGIN_IP_WINDOW = 60  # 秒

# ---------------- 密码哈希 ----------------

def hash_password(password: str) -> str:
    """用 scrypt 对密码做加盐哈希，返回 `scrypt$salt$hash`。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """常量时间校验密码；格式异常一律返回 False。"""
    try:
        _algo, salt_hex, hash_hex = stored.split("$")
        if _algo != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return hmac.compare_digest(dk, expected)


# ---------------- 会话令牌 ----------------

def new_session_token() -> str:
    """生成 32 字节 URL 安全随机令牌（写入 Cookie 的原始值）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """令牌的 SHA-256 十六进制哈希（仅此值入库）。"""
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, user_id: int) -> str:
    """为用户创建会话，返回待写入 Cookie 的原始令牌。"""
    from app.models.user import Session

    token = new_session_token()
    db.add(
        Session(
            token_hash=hash_token(token),
            user_id=user_id,
            expires_at=now() + timedelta(seconds=SESSION_MAX_AGE_SECONDS),
        )
    )
    db.commit()
    return token


def get_user_from_token(token: str):
    """按令牌查找有效会话对应的用户；无效/过期返回 None。"""
    from app.models.user import Session, User

    if not token:
        return None
    db = SessionLocal()
    try:
        sess = db.query(Session).filter(Session.token_hash == hash_token(token)).first()
        if sess is None:
            return None
        if sess.expires_at < now():
            db.delete(sess)
            db.commit()
            return None
        return db.get(User, sess.user_id)
    finally:
        db.close()


def set_session_cookie(response, token: str, secure: bool) -> None:
    """把会话令牌写入 HttpOnly + SameSite=Lax 的 Cookie。"""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# ---------------- 登录限流 ----------------

_attempts_user: dict[str, list[float]] = {}
_attempts_ip: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()


def _prune(d: dict[str, list[float]], window: int, now_ts: float) -> None:
    """清理限流字典中已过期的条目，避免内存无限增长。

    Args:
        d: 限流记录字典（key → 时间戳列表）。
        window: 窗口时长（秒）；最后一次记录超过 2 倍窗口视为过期。
        now_ts: 当前时间戳。
    """
    for key in [k for k, v in d.items() if not v or now_ts - v[-1] > window * 2]:
        d.pop(key, None)


def login_rate_allowed(username: str, ip: str) -> bool:
    """登录限流：按用户名 + 按 IP 双维度；超限返回 False（触发 429）。"""
    now_ts = time.time()
    with _attempts_lock:
        _prune(_attempts_user, _LOGIN_USER_WINDOW, now_ts)
        _prune(_attempts_ip, _LOGIN_IP_WINDOW, now_ts)

        ulist = _attempts_user.setdefault(username, [])
        ulist[:] = [t for t in ulist if now_ts - t < _LOGIN_USER_WINDOW]
        if len(ulist) >= _LOGIN_USER_MAX:
            return False

        ilist = _attempts_ip.setdefault(ip, [])
        ilist[:] = [t for t in ilist if now_ts - t < _LOGIN_IP_WINDOW]
        if len(ilist) >= _LOGIN_IP_MAX:
            return False

        ulist.append(now_ts)
        ilist.append(now_ts)
        return True


def client_ip(request: Request) -> str:
    """尽力取客户端 IP（有反代时优先 X-Forwarded-For 首项）。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
