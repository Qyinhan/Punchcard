"""API 请求/响应数据模型：签到日志相关。"""
from datetime import datetime

from pydantic import BaseModel


class LogOut(BaseModel):
    """单条签到日志响应体。"""

    id: int
    account_id: int
    account_name: str
    platform: str
    status: str
    message: str
    source: str
    executed_at: datetime
    duration_ms: int

    model_config = {"from_attributes": True}


class LogPage(BaseModel):
    """日志分页响应体。"""

    total: int
    items: list[LogOut]
