"""签到日志 API 路由：分页查询与条件清空。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import CheckinLog
from app.schemas.log import LogOut, LogPage

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _build_filters(
    account_id: int | None, platform: str | None, status: str | None
) -> list:
    """按可选条件构造日志查询过滤条件，供查询与清空共用。

    Args:
        account_id: 按账户过滤（可选）。
        platform: 按平台过滤（可选）。
        status: 按状态过滤（可选）。

    Returns:
        SQLAlchemy 过滤条件列表。
    """
    filters = []
    if account_id is not None:
        filters.append(CheckinLog.account_id == account_id)
    if platform:
        filters.append(CheckinLog.platform == platform)
    if status:
        filters.append(CheckinLog.status == status)
    return filters


@router.get("", response_model=LogPage)
def list_logs(
    account_id: int | None = None,
    platform: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> LogPage:
    """分页查询日志，支持按账户 / 平台 / 状态过滤，按执行时间倒序。

    Args:
        account_id: 按账户过滤（可选）。
        platform: 按平台过滤（可选）。
        status: 按状态过滤（可选）。
        page: 页码，从 1 开始。
        page_size: 每页条数。
        db: 数据库会话（依赖注入）。

    Returns:
        分页结果 LogPage。
    """
    filters = _build_filters(account_id, platform, status)
    total = db.execute(select(func.count()).select_from(CheckinLog).where(*filters)).scalar_one()
    items = (
        db.execute(
            select(CheckinLog)
            .where(*filters)
            .order_by(CheckinLog.executed_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return LogPage(total=total, items=[LogOut.model_validate(i) for i in items])


@router.delete("", status_code=204)
def clear_logs(account_id: int | None = None, db: Session = Depends(get_db)) -> None:
    """按条件清空日志（account_id 为空时清空全部）。

    Args:
        account_id: 指定账户则只清空该账户的日志。
        db: 数据库会话（依赖注入）。
    """
    db.execute(delete(CheckinLog).where(*_build_filters(account_id, None, None)))
    db.commit()
