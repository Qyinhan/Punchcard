"""插件 ORM 模型：持久化平台插件注册信息与启用状态。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import now
from app.core.database import Base


class Plugin(Base):
    """插件注册表状态：记录平台插件及其启用状态。"""

    __tablename__ = "plugins"

    platform: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
