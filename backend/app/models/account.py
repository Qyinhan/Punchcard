"""账户 ORM 模型：持久化各平台签到账户及其凭证。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import now
from app.core.database import Base


class Account(Base):
    """平台签到账户，包含凭证、签到时间与跨进程签到锁字段。"""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    # Fernet 加密后的凭证 JSON
    credentials: Mapped[str] = mapped_column(Text)
    # 插件自定义的额外配置（明文 JSON，如签到时间、提醒渠道等）
    extra_config: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 每日签到时间 HH:MM
    schedule_time: Mapped[str] = mapped_column(String(5), default="08:00")
    last_checkin_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 跨进程签到锁：running 表示某进程正在执行签到（防多进程重复触发）
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    running_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
