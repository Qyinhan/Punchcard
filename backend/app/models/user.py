"""后台用户与会话 ORM 模型。

User 存储管理员账户（仅 scrypt 哈希，不存明文密码）；
Session 存储登录会话令牌的 SHA-256 哈希（原始令牌只写入浏览器 Cookie）。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import now
from app.core.database import Base


class User(Base):
    """后台登录用户（目前为单管理员）。密码仅存 scrypt 哈希。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Session(Base):
    """登录会话。仅存令牌的 SHA-256 哈希，原始令牌只写入浏览器 Cookie。"""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
