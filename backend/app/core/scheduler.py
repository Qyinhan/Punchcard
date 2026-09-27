"""
定时任务调度中枢。

基于 APScheduler 管理签到任务触发逻辑，利用进程内锁与数据库锁双重机制
避免并发冲突，通过轮询数据库状态实现账户的自动化执行。
"""
import json
import logging
import threading
import time
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from cryptography.fernet import InvalidToken
from sqlalchemy import or_, select, update

from app.core.config import TIMEZONE, now
from app.core.database import session_scope
from app.core.security import decrypt_json
from app.models import Account, CheckinLog

from app.plugins.registry import registry

logger = logging.getLogger(__name__)

# 每账户一把进程内锁：快速拦截同一进程内的并发触发
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()

# 签到一次运行的最长时间；超过视为进程已崩溃，锁可被抢占
_RUN_MAX_SECONDS = 15 * 60
# 自动签到防重复窗口：同一账户在窗口内已成功签到则跳过再次自动触发
_AUTO_DEDUP_SECONDS = 5 * 60


def _account_lock(account_id: int) -> threading.Lock:
    """获取（必要时创建）账户对应的进程内锁。

    Args:
        account_id: 账户 ID。

    Returns:
        该账户的排他锁。
    """
    with _locks_guard:
        return _locks.setdefault(account_id, threading.Lock())


def release_account_resources(account_id: int) -> None:
    """清理账户相关的内存资源（账户删除时调用）。

    Args:
        account_id: 待清理的账户 ID。
    """
    with _locks_guard:
        _locks.pop(account_id, None)


def run_checkin(account_id: int, source: str = "auto") -> CheckinLog | None:
    """
    执行单次签到流（供定时任务与手动触发共用），并返回写入的日志。

    双重防重入：
    1. 进程内锁（_locks）：防止同一进程内定时/手动触发对同一账户并发执行
    2. 数据库锁（account.running）：防止多进程各自触发时重复执行

    Args:
        account_id: 待签到账户 ID。
        source: 触发来源，``auto`` 表示定时任务，``manual`` 表示手动触发。

    Returns:
        本次签到写入的日志；被并发拦截或无账户时返回 None。
    """
    lock = _account_lock(account_id)
    if not lock.acquire(blocking=False):
        logger.info("账户 %s 正在签到中，跳过本次触发 (%s)", account_id, source)
        return None

    acquired = False
    try:
        acquired = _acquire_db_lock(account_id, source)
        if not acquired:
            return None
        return _execute(account_id, source)
    finally:
        if acquired:
            _release_db_lock(account_id)
        lock.release()


def _acquire_db_lock(account_id: int, source: str) -> bool:
    """以原子 UPDATE 抢占账户签到锁。

    已被其它进程占用或（自动触发时）近期已签到则放弃。

    Args:
        account_id: 账户 ID。
        source: 触发来源。

    Returns:
        抢占成功返回 True，否则 False。
    """
    cutoff = now() - timedelta(seconds=_RUN_MAX_SECONDS)
    with session_scope() as db:
        acc = db.get(Account, account_id)
        if acc is None:
            logger.warning("账户不存在: id=%s", account_id)
            return False
        # 自动触发：若近期已成功签到（含手动），不再重复自动执行
        if source == "auto" and acc.last_checkin_at is not None:
            # 同一自然日已签到，跳过自动触发（彻底避免动态调整时间导致的同天重跑）
            if acc.last_checkin_at.date() == now().date():
                logger.info("账户 %s 今日已签到，跳过自动触发 (%s)", account_id, source)
                return False
            delta = now() - acc.last_checkin_at
            if delta.total_seconds() < _AUTO_DEDUP_SECONDS:
                logger.info("账户 %s 近期已签到，跳过自动触发 (%s)", account_id, source)
                return False
        res = db.execute(
            update(Account)
            .where(
                Account.id == account_id,
                or_(
                    Account.running.is_(False),
                    Account.running_since.is_(None),
                    Account.running_since < cutoff,
                ),
            )
            .values(running=True, running_since=now())
        )
        db.commit()
        if res.rowcount != 1:
            logger.info("账户 %s 的签到锁被其它进程占用，跳过 (%s)", account_id, source)
            return False
        return True


def _release_db_lock(account_id: int) -> None:
    """释放账户的数据库签到锁；失败仅记录日志，不向上抛出。

    Args:
        account_id: 账户 ID。
    """
    try:
        with session_scope() as db:
            acc = db.get(Account, account_id)
            if acc is not None:
                acc.running = False
                acc.running_since = None
                db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("释放账户签到锁失败 account_id=%s", account_id)


def _execute(account_id: int, source: str) -> CheckinLog | None:
    """内部签到执行逻辑。

    从数据库读取账户信息及凭证，定位并调用对应插件进行实际操作。
    统一处理异常捕获与日志落库，保证签到流的健壮性。

    Args:
        account_id: 账户 ID。
        source: 触发来源。

    Returns:
        本次签到写入的日志；账户不存在或异常导致无法落库时返回 None。
    """
    from app.plugins.base import CheckinResult

    started = time.time()
    try:
        with session_scope() as db:
            account = db.get(Account, account_id)
            if account is None:
                logger.warning("账户不存在: id=%s", account_id)
                return None
            plugin = registry.get(account.platform)
            if not registry.is_enabled(account.platform):
                # 插件已停用：记录失败日志，不执行
                log = CheckinLog(
                    account_id=account.id,
                    account_name=account.name,
                    platform=account.platform,
                    status="failed",
                    message="插件已停用，跳过签到",
                    source=source,
                    duration_ms=0,
                )
                db.add(log)
                db.commit()
                return log
            try:
                credentials = decrypt_json(account.credentials)
            except (InvalidToken, Exception):  # noqa: BLE001
                # 凭证解密失败（密钥变更或数据损坏）：记录失败日志，不崩溃调度器
                log = CheckinLog(
                    account_id=account.id,
                    account_name=account.name,
                    platform=account.platform,
                    status="failed",
                    message="凭证解密失败，请重新配置或检查密钥",
                    source=source,
                    duration_ms=0,
                )
                db.add(log)
                db.commit()
                return log
            extra = json.loads(account.extra_config or "{}")
            result: CheckinResult = plugin.checkin(credentials, extra)
            status = "success" if result.success else "failed"
            log = CheckinLog(
                account_id=account.id,
                account_name=account.name,
                platform=account.platform,
                status=status,
                message=result.message[:2000],
                source=source,
                duration_ms=int((time.time() - started) * 1000),
            )
            db.add(log)
            if result.success:
                account.last_checkin_at = now()
                # 签到成功后，允许插件重新规划下一次执行时间（如在 extra 中记录 next_schedule_time 防风控）
                updated_extra = plugin.on_schedule_time_set(account.schedule_time, extra)
                account.extra_config = json.dumps(updated_extra, ensure_ascii=False)
                db.add(account)
                next_time = updated_extra.get("next_schedule_time", account.schedule_time)
                logger.info("账户 %s 下次签到时间已规划为 %s（基准 %s）", account.id, next_time, account.schedule_time)
            db.commit()
            return log
    except Exception as exc:  # noqa: BLE001  任何异常都记录为失败日志
        logger.exception("签到异常 account_id=%s", account_id)
        try:
            with session_scope() as db:
                account = db.get(Account, account_id)
                log = CheckinLog(
                    account_id=account_id,
                    account_name=account.name if account else str(account_id),
                    platform=account.platform if account else "unknown",
                    status="failed",
                    message=f"执行异常: {exc}"[:2000],
                    source=source,
                    duration_ms=int((time.time() - started) * 1000),
                )
                db.add(log)
        except Exception:  # noqa: BLE001
            logger.exception("写入失败日志异常 account_id=%s", account_id)
        return None


class SchedulerService:
    """全局调度器服务封装。

    维护 BackgroundScheduler 实例生命周期，作为单例服务隐藏底层定时器细节，
    对外暴露安全的启停接口。
    """

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(timezone=TIMEZONE)

    def start(self) -> None:
        """启动每分钟一次的签到扫描任务。"""
        self._scheduler.add_job(
            self._tick,
            "interval",
            minutes=1,
            id="checkin_tick",
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.start()
        logger.info("调度器已启动")

    def shutdown(self) -> None:
        """关闭调度器（不等待正在执行的任务）。"""
        self._scheduler.shutdown(wait=False)

    def _tick(self) -> None:
        """每分钟扫描一次，找到到点的账户并触发签到。"""
        hhmm = now().strftime("%H:%M")
        today = now().date()
        logger.debug("调度扫描 %s", hhmm)
        matched_ids: list[int] = []
        with session_scope() as db:
            accounts = db.execute(
                select(Account).where(Account.enabled.is_(True))
            ).scalars().all()
            for acc in accounts:
                if not registry.is_enabled(acc.platform):
                    continue  # 平台插件已停用，跳过
                if acc.running:
                    continue  # 正在执行签到中，跳过
                if acc.last_checkin_at is not None and acc.last_checkin_at.date() == today:
                    continue  # 今日已完成签到，跳过
                extra = json.loads(acc.extra_config or "{}")
                effective_time = extra.get("next_schedule_time") or acc.schedule_time
                if effective_time == hhmm:
                    matched_ids.append(acc.id)
        for account_id in matched_ids:
            # 已捕获异常，无需等待结果
            self._scheduler.add_job(
                run_checkin,
                args=[account_id, "auto"],
                id=f"auto_{account_id}_{int(time.time())}",
                coalesce=True,
                max_instances=1,
            )


scheduler_service = SchedulerService()
