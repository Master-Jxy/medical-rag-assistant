"""健康检查接口的数据结构。"""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """健康检查成功时返回的数据。"""

    status: Literal["ok"]
