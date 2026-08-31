"""
后端服务启动入口：加载配置并启动 Uvicorn 服务器。

默认关闭热重载：热重载在 Windows 下会随文件变更累积出多个后端进程，
导致同一分钟的定时签到被重复触发。需要开发热重载时设 PUNCHCARD_RELOAD=1。
"""
import os

import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    reload = os.environ.get("PUNCHCARD_RELOAD") == "1"
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=reload)
