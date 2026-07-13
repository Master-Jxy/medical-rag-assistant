"""兼容旧启动方式的入口。

正式的 FastAPI 应用位于 ``app/main.py``。保留这个文件可以让初学阶段从
PyCharm 直接运行或导入 ``main:app``，但推荐使用 README 中的标准命令启动。
"""

from app.main import app

__all__ = ["app"]
