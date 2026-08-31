"""后台任务注册表：用于登录、同步好友等需要交互/耗时的操作。

同一账户同一时刻只允许一个任务在跑，前端通过轮询 GET /api/jobs/{id} 获取结果。
"""
import logging
import threading
import time
import uuid
from collections.abc import Callable

logger = logging.getLogger(__name__)


class Job:
    """轻量级后台任务状态承载实体。

    用于追踪长耗时或需外部交互的任务的状态与结果，供前端轮询消费。
    """

    __slots__ = ("job_id", "kind", "account_id", "status", "result", "error", "created_at")

    def __init__(self, job_id: str, kind: str, account_id: int) -> None:
        self.job_id = job_id
        self.kind = kind
        self.account_id = account_id
        self.status = "running"  # running / success / failed
        self.result = None
        self.error = None
        self.created_at = time.time()


_jobs: dict[str, Job] = {}
_guard = threading.Lock()
_MAX_JOBS = 50


def start_job(kind: str, account_id: int, fn: Callable, *args) -> str:
    """启动后台任务，分配 job_id 并入池管理。

    采用内存排他锁设计：同一账户已有运行中任务时抛出 RuntimeError，
    阻止重复执行。任务在守护线程中运行，不阻塞调用方。

    Args:
        kind: 任务类型标识（如 ``sync_friends``）。
        account_id: 归属账户 ID，用于互斥判断。
        fn: 实际执行的函数。
        *args: 传给 ``fn`` 的位置参数。

    Returns:
        新任务的 job_id，用于后续查询状态。

    Raises:
        RuntimeError: 该账户已有任务正在运行。
    """
    with _guard:
        if any(j.account_id == account_id and j.status == "running" for j in _jobs.values()):
            raise RuntimeError("该账户已有任务正在运行，请稍后再试")
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = Job(job_id, kind, account_id)
        # 简单清理：按完成时间淘汰最旧的已完成任务，最多保留 _MAX_JOBS 个
        done = sorted(
            (j for j in _jobs.values() if j.status != "running"),
            key=lambda j: j.created_at,
        )
        while len(_jobs) > _MAX_JOBS and done:
            _jobs.pop(done.pop(0).job_id, None)
    threading.Thread(target=_run_job, args=(job_id, fn, args), daemon=True).start()
    return job_id


def _run_job(job_id: str, fn: Callable, args: tuple) -> None:
    """在后台线程中实际执行任务，并回写状态，避免阻塞主线程。

    Args:
        job_id: 任务 ID。
        fn: 待执行的函数。
        args: 传给 ``fn`` 的位置参数。
    """
    job = _jobs[job_id]
    try:
        job.result = fn(*args)
        job.status = "success"
    except Exception as exc:  # noqa: BLE001  任务失败统一回写 error，不中断进程
        logger.exception("任务 %s（%s）失败", job_id, job.kind)
        job.error = str(exc)
        job.status = "failed"


def get_job(job_id: str) -> Job | None:
    """按 job_id 查询任务状态。

    Args:
        job_id: 任务 ID。

    Returns:
        任务实体；不存在时返回 None。
    """
    return _jobs.get(job_id)
