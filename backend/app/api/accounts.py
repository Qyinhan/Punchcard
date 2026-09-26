"""账户管理 API 路由：账户的增删改查、手动签到与交互式登录会话。"""
import json
import logging
import re
import threading
import time

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, session_scope
from app.core.security import decrypt_json, encrypt_json
from app.models import Account
from app.plugins.registry import registry
from app.schemas.account import AccountCreate, AccountOut, AccountUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

# ---- 交互式登录会话（每个账户至多一个，全局同时只有一个进行中）----
_login_sessions: dict[int, object] = {}
_login_sessions_lock = threading.Lock()
_saved_logins: set[int] = set()
# 登录会话最长存活时间（秒）；超时自动清理，避免残留阻塞后续登录
_LOGIN_SESSION_TTL = 10 * 60


def _get_plugin(platform: str):
    """取插件；平台未注册（如插件依赖缺失被跳过）时返回 400 而非 500。

    Args:
        platform: 平台标识。

    Returns:
        对应的插件实例。

    Raises:
        HTTPException: 平台未注册时抛出 400。
    """
    try:
        return registry.get(platform)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _get_account_or_404(db: Session, account_id: int) -> Account:
    """按 ID 取账户，不存在时抛出 404。

    Args:
        db: 数据库会话。
        account_id: 账户 ID。

    Returns:
        账户 ORM 对象。

    Raises:
        HTTPException: 账户不存在时抛出 404。
    """
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "账户不存在")
    return acc


def _decrypt_safe(raw: str) -> dict:
    """解密凭证；密钥变更导致无法解密时降级为空 dict，避免整个接口 500。

    Args:
        raw: 加密的凭证字符串。

    Returns:
        解密后的凭证 dict；为空或解密失败时返回 {}。
    """
    if not raw:
        return {}
    try:
        return decrypt_json(raw)
    except InvalidToken:
        return {}


def _to_out(acc: Account) -> AccountOut:
    """把 ORM 账户转换为响应体，仅回显非敏感凭证字段。

    Args:
        acc: 账户 ORM 对象。

    Returns:
        可用于响应序列化的 AccountOut。
    """
    creds = _decrypt_safe(acc.credentials)
    # 仅回显非敏感凭证字段（如登录手机号），Cookie 等敏感值不返回；
    # credential_keys 也只暴露非敏感字段名，避免泄露内部凭证结构
    safe = {}
    safe_keys = []
    try:
        plugin = registry.get(acc.platform)
        non_secret = {f.key for f in plugin.credential_fields if not f.sensitive}
        safe = {k: v for k, v in creds.items() if k in non_secret}
        safe_keys = list(safe.keys())
    except ValueError:
        pass
    return AccountOut(
        id=acc.id,
        platform=acc.platform,
        name=acc.name,
        enabled=acc.enabled,
        schedule_time=acc.schedule_time,
        has_credentials=bool(acc.credentials),
        credential_keys=safe_keys,
        credentials=safe,
        extra_config=json.loads(acc.extra_config) if acc.extra_config else {},
        last_checkin_at=acc.last_checkin_at,
        created_at=acc.created_at,
    )


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)) -> list[AccountOut]:
    """列出全部账户（按创建时间升序）。"""
    accounts = db.execute(select(Account).order_by(Account.created_at)).scalars().all()
    return [_to_out(a) for a in accounts]


@router.post("", response_model=AccountOut, status_code=201)
def create_account(data: AccountCreate, db: Session = Depends(get_db)) -> AccountOut:
    """创建新账户：校验平台注册与凭证，并加密存储。"""
    if not registry.has(data.platform):
        raise HTTPException(400, f"未注册的平台: {data.platform}")
    if not registry.is_enabled(data.platform):
        raise HTTPException(400, f"该平台插件已停用: {data.platform}")
    plugin = registry.get(data.platform)
    try:
        plugin.validate(data.credentials)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    schedule_time = data.schedule_time or plugin.default_schedule_time
    # 统一校验最终写入的调度时间格式（插件 default_schedule_time 可能格式有误）
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", schedule_time):
        raise HTTPException(400, f"无效的调度时间格式（需为 HH:MM）: {schedule_time!r}")
    # 插件扩展：记录基准时间并计算实际调度时间（如随机抖动防风控）
    extra_config = dict(data.extra_config)
    schedule_time, extra_config = plugin.on_schedule_time_set(schedule_time, extra_config)
    acc = Account(
        platform=data.platform,
        name=data.name,
        credentials=encrypt_json(data.credentials),
        extra_config=json.dumps(extra_config, ensure_ascii=False),
        enabled=data.enabled,
        schedule_time=schedule_time,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return _to_out(acc)


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int, db: Session = Depends(get_db)) -> AccountOut:
    """获取单个账户详情。"""
    return _to_out(_get_account_or_404(db, account_id))


@router.put("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int, data: AccountUpdate, db: Session = Depends(get_db)
) -> AccountOut:
    """部分更新账户：凭证采用合并语义，避免部分更新时丢失其它字段。"""
    acc = _get_account_or_404(db, account_id)
    if data.name is not None:
        acc.name = data.name
    if data.credentials is not None:
        # 与已有凭证合并，避免部分更新时丢失其它字段；合并后整体校验
        merged = _decrypt_safe(acc.credentials)
        merged.update(data.credentials)
        plugin = _get_plugin(acc.platform)
        try:
            plugin.validate(merged)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        acc.credentials = encrypt_json(merged)
    if data.extra_config is not None:
        acc.extra_config = json.dumps(data.extra_config, ensure_ascii=False)
    if data.enabled is not None:
        acc.enabled = data.enabled
    if data.schedule_time is not None:
        plugin = _get_plugin(acc.platform)
        current_extra = json.loads(acc.extra_config or "{}")
        schedule_time, updated_extra = plugin.on_schedule_time_set(data.schedule_time, current_extra)
        acc.schedule_time = schedule_time
        acc.extra_config = json.dumps(updated_extra, ensure_ascii=False)
    db.commit()
    db.refresh(acc)
    return _to_out(acc)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)) -> None:
    """删除账户并清理其进程内签到锁等内存资源。"""
    from app.core.scheduler import release_account_resources

    acc = _get_account_or_404(db, account_id)
    db.delete(acc)
    db.commit()
    release_account_resources(account_id)


@router.post("/{account_id}/checkin")
def trigger_checkin(account_id: int, db: Session = Depends(get_db)) -> dict:
    """手动触发一次签到，同步等待结果。"""
    from app.core.scheduler import run_checkin

    _get_account_or_404(db, account_id)
    log = run_checkin(account_id, source="manual")
    if log is None:
        raise HTTPException(409, "该账户正在签到中或执行异常，请稍后重试并查看日志")
    return {"log_id": log.id, "status": log.status, "message": log.message}


@router.post("/{account_id}/login")
def start_login(
    account_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
) -> dict:
    """启动交互式登录会话并请求发送验证码；前端随后轮询状态。

    仅允许同时存在一个进行中的登录会话（任何账户），避免多个无头浏览器并存。
    """
    acc = _get_account_or_404(db, account_id)
    plugin = _get_plugin(acc.platform)
    if not plugin.login_supported:
        raise HTTPException(400, "该平台不支持自动登录")
    phone = str((payload or {}).get("phone", "")).strip()
    if not phone:
        raise HTTPException(400, "请填写登录手机号")
    session = plugin.create_login_session(account_id)
    with _login_sessions_lock:
        _cleanup_stale_sessions_unsafe()
        # 同账户残留的旧会话（如上次未取消）自动替换，避免重复触发时误报 409
        old = _login_sessions.pop(account_id, None)
        if old is not None:
            try:
                old.close()
            except Exception:  # noqa: BLE001
                logger.warning("关闭残留登录会话失败（账户 %s）", account_id)
        # 原子检查：其他账户无进行中会话
        for s in _login_sessions.values():
            if s.status().get("stage") not in ("success", "failed"):
                raise HTTPException(409, "已有登录会话进行中，请先完成或取消")
        _login_sessions[account_id] = session
    session.start()
    session.send_code(phone)
    return {"ok": True, "stage": "initializing"}


@router.post("/{account_id}/login/qr")
def start_qr_login(account_id: int, db: Session = Depends(get_db)) -> dict:
    """启动扫码登录：无头浏览器切到二维码，前端展示二维码并轮询状态。"""
    acc = _get_account_or_404(db, account_id)
    plugin = _get_plugin(acc.platform)
    if not plugin.login_supported:
        raise HTTPException(400, "该平台不支持自动登录")
    session = plugin.create_login_session(account_id)
    with _login_sessions_lock:
        _cleanup_stale_sessions_unsafe()
        # 同账户残留的旧会话（如上次关闭页面未取消）自动替换，避免「刷新二维码」永远 409
        old = _login_sessions.pop(account_id, None)
        if old is not None:
            try:
                old.close()
            except Exception:  # noqa: BLE001
                logger.warning("关闭残留登录会话失败（账户 %s）", account_id)
        # 原子检查：其他账户无进行中会话（检查与写入在同一锁块内，消除 TOCTOU）
        for s in _login_sessions.values():
            if s.status().get("stage") not in ("success", "failed"):
                raise HTTPException(409, "已有登录会话进行中，请先完成或取消")
        _login_sessions[account_id] = session
    session.start()
    session.show_qr()
    return {"ok": True, "stage": "initializing"}


@router.get("/{account_id}/login")
def login_status(account_id: int) -> dict:
    """查询登录会话状态；成功后自动把 Cookie 保存到账户凭证。"""
    session = _get_login_session(account_id)
    if session is None:
        raise HTTPException(404, "无登录会话")
    state = dict(session.status())
    if state.get("stage") in ("success", "failed"):
        # 原子标记：并发轮询下只保存一次 Cookie。
        # 先加标记再移除会话：确保两个并发请求中只有第一个进锁的执行保存，
        # 第二个看到 already_saved=True 后跳过，且 session 已被 pop 后续请求直接 404。
        with _login_sessions_lock:
            already_saved = account_id in _saved_logins
            if not already_saved:
                _saved_logins.add(account_id)
            _login_sessions.pop(account_id, None)
        if not already_saved:
            _save_login_cookies(account_id, state.get("cookies") or [])
            logger.info("账户 %s 登录成功，Cookie 已保存", account_id)
            # 重置去重标记，使账户下次登录仍能触发保存；
            # 放在保存完成后、锁内执行，防止并发轮询提前清除标记
            with _login_sessions_lock:
                _saved_logins.discard(account_id)
    return {"account_id": account_id, **state}


@router.post("/{account_id}/login/captcha")
def solve_captcha(account_id: int, payload: dict = Body(default={})) -> dict:
    """提交人机验证（抖音拖滑块 / B 站极验）结果。"""
    session = _require_login_session(account_id)
    session.solve_captcha(**(payload or {}))
    return {"ok": True, "stage": "initializing"}


@router.post("/{account_id}/login/code")
def submit_code(account_id: int, payload: dict = Body(default={})) -> dict:
    """提交短信验证码完成登录。"""
    session = _require_login_session(account_id)
    code = str((payload or {}).get("code", "")).strip()
    if not code:
        raise HTTPException(400, "请输入验证码")
    session.submit_code(code)
    return {"ok": True, "stage": "initializing"}


@router.delete("/{account_id}/login")
def cancel_login(account_id: int) -> dict:
    """取消进行中的登录会话并清理内存状态。"""
    session = _get_login_session(account_id)
    if session is None:
        raise HTTPException(404, "无登录会话")
    session.close()
    with _login_sessions_lock:
        _login_sessions.pop(account_id, None)
    _saved_logins.discard(account_id)
    return {"ok": True}


def _get_login_session(account_id: int):
    """线程安全地获取账户的登录会话。

    Args:
        account_id: 账户 ID。

    Returns:
        登录会话对象；不存在时返回 None。
    """
    with _login_sessions_lock:
        return _login_sessions.get(account_id)


def _require_login_session(account_id: int):
    """获取账户登录会话，不存在时抛出 404。

    Args:
        account_id: 账户 ID。

    Returns:
        登录会话对象。

    Raises:
        HTTPException: 无登录会话时抛出 404。
    """
    session = _get_login_session(account_id)
    if session is None:
        raise HTTPException(404, "无登录会话")
    return session


def _cleanup_stale_sessions_unsafe() -> None:
    """清理超时的登录会话（必须在持有 _login_sessions_lock 时调用）。

    将已超过 _LOGIN_SESSION_TTL 的会话关闭并移除，防止用户关掉页面/对话框
    但未调取消接口时，残留的会话长期占用「唯一登录会话」名额而导致 409。
    """
    now = time.time()
    stale = [
        aid for aid, s in _login_sessions.items()
        if now - getattr(s, "_created_at", now) > _LOGIN_SESSION_TTL
    ]
    for aid in stale:
        try:
            _login_sessions[aid].close()
        except Exception:  # noqa: BLE001
            pass
        _login_sessions.pop(aid, None)
        logger.info("已清理超时的登录会话（账户 %s）", aid)


def _save_login_cookies(account_id: int, cookies: list) -> None:
    """登录成功后把 Cookie 合并写入账户凭证。

    Args:
        account_id: 账户 ID。
        cookies: 登录接口返回的 Cookie 列表。
    """
    if not cookies:
        return
    with session_scope() as db:
        acc = db.get(Account, account_id)
        if acc is None:
            return
        creds = _decrypt_safe(acc.credentials)
        creds["cookies"] = json.dumps(cookies, ensure_ascii=False)
        acc.credentials = encrypt_json(creds)
        # 显式 add 确保 SQLAlchemy 追踪到字段变更，使 commit 时正确持久化
        db.add(acc)
    logger.info("账户 %s 的登录 Cookie 已保存（%d 个）", account_id, len(cookies))


@router.post("/{account_id}/sync-friends")
def start_sync_friends(account_id: int, db: Session = Depends(get_db)) -> dict:
    """启动同步好友列表任务（使用已保存的凭证），返回 job_id 供轮询。"""
    from app.core.jobs import start_job

    acc = _get_account_or_404(db, account_id)
    plugin = _get_plugin(acc.platform)
    if not plugin.friends_supported:
        raise HTTPException(400, "该平台不支持同步好友")
    try:
        job_id = start_job("sync_friends", account_id, _run_sync_job, account_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return {"job_id": job_id}


def _run_sync_job(account_id: int) -> dict:
    """后台执行同步好友：拉取好友列表并写入账户的 extra_config。

    Args:
        account_id: 账户 ID。

    Returns:
        包含好友列表的 dict，如 ``{"friends": [...]}``。

    Raises:
        RuntimeError: 账户不存在时抛出。
    """
    with session_scope() as db:
        acc = db.get(Account, account_id)
        if acc is None:
            raise RuntimeError("账户不存在")
        plugin = registry.get(acc.platform)
        creds = _decrypt_safe(acc.credentials)
    friends = plugin.list_friends(creds)
    with session_scope() as db:
        acc = db.get(Account, account_id)
        if acc is not None:
            extra = json.loads(acc.extra_config or "{}")
            extra["friends"] = friends
            acc.extra_config = json.dumps(extra, ensure_ascii=False)
            # 显式 add 确保 SQLAlchemy 追踪到字段变更，使 commit 时正确持久化
            db.add(acc)
    return {"friends": friends}
