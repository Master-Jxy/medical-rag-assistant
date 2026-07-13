"""所有 SQLAlchemy 模型共同继承的基类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base.metadata 汇总全部模型表结构。"""
