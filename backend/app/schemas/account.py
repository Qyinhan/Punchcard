"""API 请求/响应数据模型：账户相关。"""
from datetime import datetime

from pydantic import BaseModel, Field

# 调度器按 %H:%M 匹配，非法格式会导致任务永远静默不触发
_SCHEDULE_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class AccountCreate(BaseModel):
    """新建账户请求体。"""

    platform: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    credentials: dict
    extra_config: dict = {}
    enabled: bool = True
    # 不传则使用插件默认时间
    schedule_time: str | None = Field(default=None, pattern=_SCHEDULE_PATTERN)


class AccountUpdate(BaseModel):
    """部分更新账户请求体（各字段均可选）。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    credentials: dict | None = None
    extra_config: dict | None = None
    enabled: bool | None = None
    schedule_time: str | None = Field(default=None, pattern=_SCHEDULE_PATTERN)


class AccountOut(BaseModel):
    """账户响应体，包含非敏感凭证字段回显。"""

    id: int
    platform: str
    name: str
    enabled: bool
    schedule_time: str
    has_credentials: bool
    credential_keys: list[str] = []
    credentials: dict = {}  # 仅含非敏感字段的值（用于前端回显）
    extra_config: dict | None = None
    last_checkin_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
