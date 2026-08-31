"""插件注册表：管理安装到 `data/plugins/` 的平台插件。

所有平台都以"安装的插件"形式存在（无内置插件），可停用/启用、安装、卸载。
- 发现：扫描 data/plugins/ 下每个含 plugin.py 或 __init__.py 的子目录
- 包结构插件（含 __init__.py）按包加载，支持内部相对导入
- 启用状态持久化到 plugins 表
"""
import importlib
import importlib.util
import io
import logging
import shutil
import sys
import time
import zipfile
from pathlib import Path

from app.core.config import PLUGINS_DIR
from app.core.database import session_scope
from sqlalchemy import select

from .base import BasePlugin

logger = logging.getLogger(__name__)

_PLUGIN_ATTR = "plugin"


class PluginRegistry:
    """平台插件注册表：负责插件的发现、加载、启停持久化与安装/卸载。

    提供进程内的插件实例、启用状态及安装目录索引，所有操作线程安全级别为
    单进程单线程（FastAPI 事件循环 + 后台线程串行调用）。
    """

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}
        self._enabled: dict[str, bool] = {}
        self._dirs: dict[str, Path] = {}
        self._module_names: dict[str, str] = {}

    # ---------- 查询 ----------
    def get(self, platform: str) -> BasePlugin:
        """按平台标识获取插件实例。

        Args:
            platform: 平台标识。

        Returns:
            插件实例。

        Raises:
            ValueError: 平台未注册时抛出。
        """
        try:
            return self._plugins[platform]
        except KeyError:
            raise ValueError(f"未注册的平台: {platform}")

    def all(self) -> list[BasePlugin]:
        """返回全部已注册插件实例列表。"""
        return list(self._plugins.values())

    def has(self, platform: str) -> bool:
        """判断平台是否已注册。"""
        return platform in self._plugins

    def is_enabled(self, platform: str) -> bool:
        """判断平台插件是否启用（未记录时默认视为启用）。"""
        return self._enabled.get(platform, True)

    def describe_all(self) -> list[dict]:
        """输出全部插件的描述信息及启用状态。"""
        out = []
        for p in self._plugins.values():
            d = p.describe()
            d["enabled"] = self.is_enabled(p.platform)
            out.append(d)
        return out

    # ---------- 发现 / 加载 ----------
    def discover(self) -> None:
        """扫描用户插件目录，并同步启用状态；清理已不存在的插件记录。"""
        self._plugins.clear()
        self._enabled.clear()
        self._dirs.clear()
        self._module_names.clear()
        for sub in sorted(PLUGINS_DIR.iterdir()):
            if not sub.is_dir() or sub.name.startswith(("__", ".")):
                continue
            plugin = self._load_user_dir(sub)
            if plugin is None:
                continue
            try:
                self._register(plugin, sub)
            except ValueError as exc:
                logger.warning("跳过插件 %s: %s", sub.name, exc)
        self._sync_db()

    def _load_user_dir(self, path: Path) -> BasePlugin | None:
        """加载单个插件目录（plugin.py 或 __init__.py），返回插件实例。

        Args:
            path: 插件目录路径。

        Returns:
            插件实例；加载失败或未导出 ``plugin`` 时返回 None。
        """
        # 每次加载使用唯一模块名，避免重载时命中旧模块缓存
        module_name = f"user_plugin_{path.name}_{time.time_ns()}"
        init_file = path / "__init__.py"
        try:
            if init_file.exists():
                spec = importlib.util.spec_from_file_location(
                    module_name, init_file, submodule_search_locations=[str(path)]
                )
            else:
                plugin_file = path / "plugin.py"
                if not plugin_file.exists():
                    logger.warning("用户插件目录 %s 缺少 plugin.py 或 __init__.py", path.name)
                    return None
                spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载用户插件 %s 失败: %s", path.name, exc)
            return None
        plugin = getattr(module, _PLUGIN_ATTR, None)
        if isinstance(plugin, BasePlugin):
            self._module_names[plugin.platform] = module_name
        return plugin if isinstance(plugin, BasePlugin) else None

    def _register(self, plugin: BasePlugin, plugin_dir: Path) -> None:
        """注册插件实例到内存索引。

        Args:
            plugin: 插件实例。
            plugin_dir: 插件所在目录。

        Raises:
            ValueError: 缺少平台标识或平台标识重复时抛出。
        """
        if not plugin.platform:
            raise ValueError(f"{type(plugin).__name__} 必须定义 platform")
        if plugin.platform in self._plugins:
            raise ValueError(f"平台标识重复: {plugin.platform}")
        self._plugins[plugin.platform] = plugin
        self._dirs[plugin.platform] = plugin_dir
        self._enabled[plugin.platform] = True
        logger.info("已注册平台插件: %s (%s)", plugin.name, plugin.platform)

    # ---------- 启停持久化 ----------
    def _upsert_plugin(self, db, platform: str, name: str, enabled: bool | None = None) -> bool:
        """按平台 upsert 一行插件记录，返回最终启用的布尔值。

        Args:
            db: 数据库会话。
            platform: 平台标识。
            name: 插件名称（新建时写入，已有记录时同步更新）。
            enabled: 目标启用状态；为 None 时保留数据库已有状态。

        Returns:
            该平台最终启用的布尔值（新建行缺省视为启用）。
        """
        from app.models.plugin import Plugin

        row = db.get(Plugin, platform)
        if row is None:
            row = Plugin(
                platform=platform,
                name=name,
                enabled=True if enabled is None else bool(enabled),
            )
            db.add(row)
        else:
            if enabled is None:
                row.name = name
            else:
                row.enabled = bool(enabled)
        return bool(row.enabled)

    def _sync_db(self) -> None:
        """把注册表与数据库同步：补全新插件记录、清理已卸载记录。"""
        from app.models.plugin import Plugin

        with session_scope() as db:
            for p in self._plugins.values():
                self._enabled[p.platform] = self._upsert_plugin(db, p.platform, p.name)
            # 清理已卸载插件的记录
            for row in db.execute(select(Plugin)).scalars().all():
                if row.platform not in self._plugins:
                    db.delete(row)

    def set_enabled(self, platform: str, enabled: bool) -> None:
        """设置插件启用状态并持久化。

        Args:
            platform: 平台标识。
            enabled: 是否启用。

        Raises:
            ValueError: 平台未注册时抛出。
        """
        from app.models.plugin import Plugin

        self.get(platform)  # 校验存在
        self._enabled[platform] = bool(enabled)
        with session_scope() as db:
            self._upsert_plugin(db, platform, self._plugins[platform].name, enabled)
        logger.info("插件 %s 已%s", platform, "启用" if enabled else "停用")

    def reload(self) -> None:
        """重新扫描插件目录。"""
        self.discover()

    # ---------- 安装 / 卸载 ----------
    def install_zip(self, data: bytes, filename: str) -> dict:
        """从 ZIP 安装插件。

        校验压缩包结构、路径安全后解压到临时目录加载验证，再把插件目录
        移动到正式位置并注册。

        Args:
            data: ZIP 文件字节流。
            filename: 上传文件名（仅用于错误提示）。

        Returns:
            安装成功的插件信息 {platform, name}。

        Raises:
            RuntimeError: ZIP 无效、缺少 plugin.py/__init__.py、路径非法或
                平台标识已存在时抛出。
        """
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise RuntimeError("无效的 ZIP 文件")

        entries = [n for n in zf.namelist() if not n.endswith("/")]
        if not entries:
            raise RuntimeError("ZIP 为空")

        # 识别是否存在统一顶层目录（如 douyin/plugin.py）
        top = entries[0].split("/")[0]
        if all(n.startswith(top + "/") for n in entries) and not any("/" not in n for n in entries):
            base = top
        else:
            base = ""

        has_init = f"{base}/__init__.py" if base else "__init__.py"
        has_plugin = f"{base}/plugin.py" if base else "plugin.py"
        if has_init not in entries and has_plugin not in entries:
            raise RuntimeError("ZIP 中未找到 plugin.py / __init__.py")

        for n in entries:
            if n.startswith("/") or ".." in n.split("/"):
                raise RuntimeError(f"非法的文件路径: {n}")

        tmp = PLUGINS_DIR / f"__tmp_{time.time_ns()}"
        tmp.mkdir(parents=True, exist_ok=True)
        try:
            tmp_resolved = tmp.resolve()
            for n in entries:
                if "__pycache__" in n or n.startswith("."):
                    continue
                dest = (tmp / (n[len(base) + 1:] if base else n)).resolve()
                if not dest.is_relative_to(tmp_resolved):
                    raise RuntimeError(f"非法的文件路径: {n}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(n) as src, open(dest, "wb") as out:
                    out.write(src.read())
            plugin = self._load_user_dir(tmp)
            if plugin is None:
                raise RuntimeError("插件加载失败（需定义 plugin 实例）")
            platform = plugin.platform
            if platform in self._plugins:
                raise RuntimeError(f"平台标识已存在: {platform}")
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

        final_dir = PLUGINS_DIR / platform
        if final_dir.exists():
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"插件目录已存在: {platform}")
        shutil.move(str(tmp), str(final_dir))
        self._register(plugin, final_dir)
        self._sync_db()
        return {"platform": platform, "name": plugin.name}

    def uninstall(self, platform: str) -> None:
        """卸载插件：删除目录、移除内存索引与数据库记录。

        Args:
            platform: 平台标识。
        """
        plugin_dir = self._dirs.get(platform)
        if plugin_dir is not None:
            shutil.rmtree(plugin_dir, ignore_errors=True)
            self._dirs.pop(platform, None)
        # 从 sys.modules 清除该插件的模块及子模块，避免占用文件句柄
        for name in list(sys.modules):
            if name == self._module_names.get(platform) or (
                self._module_names.get(platform)
                and name.startswith(self._module_names[platform] + ".")
            ):
                sys.modules.pop(name, None)
        self._module_names.pop(platform, None)
        self._plugins.pop(platform, None)
        self._enabled.pop(platform, None)
        from app.models.plugin import Plugin

        with session_scope() as db:
            row = db.get(Plugin, platform)
            if row is not None:
                db.delete(row)
        logger.info("插件 %s 已卸载", platform)


registry = PluginRegistry()
