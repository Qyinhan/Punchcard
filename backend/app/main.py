"""
FastAPI 应用的主入口文件，负责初始化数据库、加载插件、注册路由以及启动后台调度任务。
该模块主要为了串联起各个独立的服务模块，形成完整的 Web 应用实例。
"""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api import accounts, auth, dashboard, jobs, logs, plugins
from app.core.auth import SESSION_COOKIE, get_user_from_token
from app.core.config import settings
from app.core.database import init_db
from app.core.scheduler import scheduler_service
from app.plugins.registry import registry

# 兼容非 UTF-8 locale 的 Linux 环境（如 LANG=C），避免中文日志/输出编码报错
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用的生命周期管理器。

    保证在应用启动时按顺序初始化数据库、加载插件并启动调度器，
    并在应用关闭时安全释放资源与后台任务。
    """
    init_db()
    registry.discover()
    scheduler_service.start()
    yield
    scheduler_service.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """所有 /api/* 接口（除 /api/auth/* 与 /api/health）均需登录会话。"""
    path = request.url.path
    protected = (
        path.startswith("/api/")
        and not path.startswith("/api/auth/")
        and path != "/api/health"
    )
    if protected and request.method != "OPTIONS":
        token = request.cookies.get(SESSION_COOKIE)
        user = await run_in_threadpool(get_user_from_token, token)
        if user is None:
            return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
        request.state.user = user
    return await call_next(request)


# 生产模式下前端由后端同源托管，无需 CORS；仅放行 vite 开发服务器来源，
# 避免任意网页跨域调用本机 API（浏览器是本机服务的主要攻击面）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(plugins.router)
app.include_router(accounts.router)
app.include_router(jobs.router)
app.include_router(logs.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    """提供一个极其轻量的健康检查接口，用于负载均衡器或监控系统确认服务存活状态。"""
    return {"status": "ok", "app": settings.app_name}


# 若前端已构建（frontend/dist 存在），则托管静态资源；
# 非 API 的未知路径回退到 index.html，以支持 SPA 的 history 路由（刷新/深链不 404）
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    _index_html = _frontend_dist / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        file = (_frontend_dist / full_path).resolve()
        if full_path and file.is_file() and file.is_relative_to(_frontend_dist):
            return FileResponse(file)
        return FileResponse(_index_html)
