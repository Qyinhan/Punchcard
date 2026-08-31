"""
应用全局配置模块。

负责加载环境变量、初始化基础目录结构及处理时区设定，为其他模块提供
单一事实来源的配置对象（``settings``）。
"""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# 项目根目录（backend/）；data 目录集中存放数据库、密钥与用户插件
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
# 用户安装的插件目录（把插件文件夹放进来，重启或点"重新加载"即生效）
PLUGINS_DIR = DATA_DIR / "plugins"
PLUGINS_DIR.mkdir(exist_ok=True)

# 调度与统计统一使用的时区（Windows 需 tzdata 包提供 IANA 时区数据）
TIMEZONE = ZoneInfo(os.getenv("PUNCHCARD_TZ", "Asia/Shanghai"))


def now() -> datetime:
    """返回配置时区下的当前时间。

    返回值为 naive datetime（不带 tzinfo），与数据库中的 DateTime 列保持
    一致，避免时区感知/不感知混用引发比较异常。

    Returns:
        配置时区下的当前时间（naive datetime）。
    """
    return datetime.now(TIMEZONE).replace(tzinfo=None)


class Settings:
    """配置管理类，集中存储系统运行所需的各类参数。

    所有配置均来自环境变量并带合理默认值，避免配置散落各处。
    """

    app_name: str = "PunchCard"
    # 默认仅监听本机回环；需局域网访问时通过 PUNCHCARD_HOST=0.0.0.0 显式开启
    host: str = os.getenv("PUNCHCARD_HOST", "127.0.0.1")
    port: int = int(os.getenv("PUNCHCARD_PORT", "8000"))
    database_url: str = os.getenv(
        "PUNCHCARD_DATABASE_URL", f"sqlite:///{DATA_DIR / 'punchcard.db'}"
    )
    # 凭证加密用密钥；未设置时会在 data 目录生成并持久化一个随机密钥
    secret_key: str = os.getenv("PUNCHCARD_SECRET_KEY", "")
    data_dir: Path = DATA_DIR


settings = Settings()
