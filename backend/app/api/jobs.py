"""后台任务状态查询 API 路由。"""
from fastapi import APIRouter, HTTPException

from app.core.jobs import get_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
def job_status(job_id: str) -> dict:
    """查询后台任务（如同步好友）的执行状态与结果。

    Args:
        job_id: 任务 ID。

    Returns:
        任务状态字典；任务不存在时抛出 404。
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "account_id": job.account_id,
        "status": job.status,
        "result": job.result,
        "error": job.error,
    }
