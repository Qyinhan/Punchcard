"""登录鉴权 REST 接口：首次初始化、登录、登出、当前用户。"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.auth import (
    SESSION_COOKIE,
    clear_session_cookie,
    client_ip,
    create_session,
    get_user_from_token,
    hash_token,
    hash_password,
    login_rate_allowed,
    record_login_failure,
    set_session_cookie,
    verify_password,
)
from app.core.database import get_db
from app.models.user import Session as SessionModel
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def _cookie_secure(request: Request) -> bool:
    """HTTPS 或显式开启时标记 Cookie Secure。"""
    if request.url.scheme == "https":
        return True
    return os.getenv("PUNCHCARD_COOKIE_SECURE") == "1"


def _users_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(User)).scalar_one()


@router.get("/setup-state")
def setup_state(db: Session = Depends(get_db)):
    """是否尚未创建管理员（仅首次部署需要初始化）。"""
    return {"setup_required": _users_count(db) == 0}


@router.post("/setup")
def setup(data: SetupIn, request: Request, db: Session = Depends(get_db)):
    """首次部署创建管理员并直接登录；已初始化则拒绝。"""
    if _users_count(db) > 0:
        raise HTTPException(403, "系统已初始化，无法重复创建管理员")
    username = data.username.strip()
    if not username:
        raise HTTPException(400, "用户名不能为空")
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise HTTPException(400, "用户名已存在")
    user = User(username=username, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    token = create_session(db, user.id)
    logger.info("已创建管理员账户: %s", username)
    response = Response()
    set_session_cookie(response, token, _cookie_secure(request))
    return response


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    """用户名密码登录，成功即种下会话 Cookie。"""
    username = data.username.strip()
    ip = client_ip(request)
    if not login_rate_allowed(username, ip):
        raise HTTPException(429, "尝试次数过多，请稍后再试")
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    ok = bool(user) and verify_password(data.password, user.password_hash)
    if not ok:
        # 仅在失败时追加限流计数，成功登录不计入，避免合法使用触发封锁
        record_login_failure(username, ip)
        logger.warning("登录失败 username=%s ip=%s", username, ip)
        raise HTTPException(401, "用户名或密码错误")
    token = create_session(db, user.id)
    logger.info("登录成功 username=%s ip=%s", username, ip)
    response = Response()
    set_session_cookie(response, token, _cookie_secure(request))
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    """注销当前会话（服务端删除令牌记录并清 Cookie）。"""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(SessionModel).where(SessionModel.token_hash == hash_token(token)))
        db.commit()
    response = Response()
    clear_session_cookie(response)
    return response


@router.get("/me")
def me(request: Request):
    """返回当前登录用户。"""
    user = get_user_from_token(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "未登录或登录已过期")
    return {"username": user.username}
