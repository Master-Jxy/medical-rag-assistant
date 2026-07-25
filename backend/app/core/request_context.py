"""请求上下文：让同一 request_id 跨 Router、Service 和基础设施传播。"""

from contextvars import ContextVar, Token
from uuid import uuid4

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    return str(uuid4())


def set_request_id(value: str) -> Token[str]:
    return _request_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)


def get_request_id() -> str:
    value = _request_id.get()
    return value or new_request_id()
