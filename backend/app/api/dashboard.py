"""仪表盘 API 路由：提供概览统计数据。"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import now
from app.core.database import get_db
from app.models import Account, CheckinLog
from app.plugins.registry import registry

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _count(db: Session, model, *filters) -> int:
    """统计满足条件的记录数。

    Args:
        db: 数据库会话。
        model: ORM 模型。
        *filters: 可选的过滤条件。

    Returns:
        记录总数。
    """
    stmt = select(func.count()).select_from(model)
    if filters:
        stmt = stmt.where(*filters)
    return db.execute(stmt).scalar_one()


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    """汇总概览统计：账户数、今日/近 7 天签到结果与插件数。

    Args:
        db: 数据库会话（依赖注入）。

    Returns:
        统计字典，含 account_total / today_success / week_success 等键。
    """
    account_total = _count(db, Account)
    account_enabled = _count(db, Account, Account.enabled.is_(True))
    today_start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_total = _count(db, CheckinLog, CheckinLog.executed_at >= today_start)
    today_success = _count(
        db,
        CheckinLog,
        CheckinLog.executed_at >= today_start,
        CheckinLog.status == "success",
    )
    week_success = _count(
        db,
        CheckinLog,
        CheckinLog.executed_at >= today_start - timedelta(days=7),
        CheckinLog.status == "success",
    )
    return {
        "account_total": account_total,
        "account_enabled": account_enabled,
        "plugin_count": len(registry.all()),
        "today_total": today_total,
        "today_success": today_success,
        "today_failed": today_total - today_success,
        "week_success": week_success,
    }
