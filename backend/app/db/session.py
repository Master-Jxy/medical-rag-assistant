"""创建数据库引擎和请求级 Session。"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(database_url: str) -> Engine:
    """根据 URL 创建引擎；测试可以传 SQLite，正式环境使用 MySQL。"""
    options: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        options["pool_recycle"] = 3600
    return create_engine(database_url, **options)


@lru_cache
def get_engine() -> Engine:
    """首次使用会话功能时才创建 MySQL 引擎，不影响其他接口启动。"""
    database_url = get_settings().require_database_url()
    return build_engine(database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """每个请求独享一个 Session，失败回滚，请求结束后关闭。"""
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
