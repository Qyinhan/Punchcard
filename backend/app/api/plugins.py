"""平台插件管理 API 路由：列表、启停、安装、重载与卸载。"""
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Account
from app.plugins.registry import registry

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("")
def list_plugins() -> list[dict]:
    """返回所有已安装的平台插件及其字段定义、启用状态。"""
    return registry.describe_all()


@router.put("/{platform}")
def set_plugin_enabled(platform: str, payload: dict = Body(default={})) -> dict:
    """启用 / 停用插件。

    停用后该平台不可新建账户，已存在的账户不再自动签到。

    Args:
        platform: 平台标识。
        payload: 请求体，含 ``enabled`` 布尔值。

    Returns:
        更新后的启用状态。
    """
    if not registry.has(platform):
        raise HTTPException(404, f"平台不存在: {platform}")
    enabled = bool((payload or {}).get("enabled", True))
    registry.set_enabled(platform, enabled)
    return {"platform": platform, "enabled": enabled}


@router.post("/install")
async def install_plugin(file: UploadFile = File(...)) -> dict:
    """通过上传 ZIP 安装用户插件。

    Args:
        file: ZIP 压缩包文件。

    Returns:
        安装成功的插件信息 {platform, name}。
    """
    data = await file.read()
    try:
        info = registry.install_zip(data, file.filename or "plugin.zip")
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return info


@router.post("/reload")
def reload_plugins() -> dict:
    """重新扫描插件目录（手动放置插件文件夹后使用）。"""
    registry.reload()
    return {"ok": True}


@router.delete("/{platform}")
def uninstall_plugin(platform: str, db: Session = Depends(get_db)) -> dict:
    """卸载插件（需先删除该平台账户）。

    Args:
        platform: 平台标识。
        db: 数据库会话（依赖注入）。
    """
    if not registry.has(platform):
        raise HTTPException(404, f"平台不存在: {platform}")
    count = db.execute(
        select(func.count()).select_from(Account).where(Account.platform == platform)
    ).scalar_one()
    if count:
        raise HTTPException(400, f"该平台还有 {count} 个账户，请先删除账户再卸载")
    registry.uninstall(platform)
    return {"ok": True}
