"""
数据库核心模块：封装 SQLAlchemy 引擎与会话管理。

提供同步的数据库会话工厂，供 FastAPI 依赖注入或后台任务独立调用。
SQLite 场景下开启 WAL 与忙碌超时，保证调度线程与请求线程并发访问的稳定性。
"""
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")


class Base(DeclarativeBase):
    """所有 ORM 模型的基类，供 SQLAlchemy 统一扫描表结构信息。"""


engine = create_engine(
    settings.database_url,
    # SQLite 默认禁止跨线程使用同一连接；关闭检查以支持后台线程访问，
    # timeout 让并发写入等待而非立刻报 "database is locked"
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        """每个新连接启用 WAL 与忙碌超时。

        WAL 允许读写并发、显著降低锁冲突；busy_timeout 使等待方阻塞等待
        而不是立即抛错。两者对多线程（请求 + 调度器）访问 SQLite 很关键。
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """
    初始化数据库表结构。

    在应用启动时调用，确保在使用数据库前所有表（对应已注册的模型）已被创建。

    Note:
        模型需先被导入注册到 ``Base.metadata``，因此这里延迟导入 ``app.models``。
    """
    from app import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI 依赖注入专用的数据库会话生成器。

    确保每个请求独享一个会话，并在请求结束时自动关闭连接。

    Yields:
        一个独立的数据库会话对象。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    提供带自动提交/回滚的事务会话。

    供调度器等非请求上下文使用：正常结束自动提交，异常时回滚并重新抛出。

    Yields:
        一个独立的数据库会话对象。
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
