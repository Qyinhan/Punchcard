"""签到日志 ORM 模型：记录每次签到执行的结果。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import now
from app.core.database import Base


class CheckinLog(Base):
    """一次签到执行记录的持久化实体。"""

    __tablename__ = "checkin_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), index=True)
    account_name: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # success / failed
    message: Mapped[str] = mapped_column(Text, default="")
    # auto / manual
    source: Mapped[str] = mapped_column(String(16), default="auto")
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
