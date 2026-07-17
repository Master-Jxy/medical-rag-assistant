"""兼容 Python 3.10 和 3.11+ 的字符串枚举。"""

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - 仅 Python 3.10 执行
    from enum import Enum

    class StrEnum(str, Enum):
        """保持 Python 3.11 StrEnum 的字符串转换行为。"""

        def __str__(self) -> str:
            return self.value


__all__ = ["StrEnum"]

