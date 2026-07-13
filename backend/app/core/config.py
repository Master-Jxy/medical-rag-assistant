"""集中读取后端配置，真实 API Key 只来自环境变量或本地 .env。"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """后端运行配置。字段名与 .env 中的环境变量名称对应。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    dashscope_api_key: SecretStr | None = Field(default=None)
    database_url: SecretStr | None = Field(default=None)
    chat_model_name: str = "qwen3-max"
    embedding_model_name: str = "text-embedding-v4"
    chroma_persist_dir: Path = BACKEND_DIR / "chroma_db"
    chroma_collection_name: str = "agent"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    document_registry_path: Path = BACKEND_DIR / "data" / "documents.json"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    chunk_size: int = 800
    chunk_overlap: int = 100
    max_history_rounds: int = 3
    max_history_chars: int = 6000
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("chroma_persist_dir", "upload_dir", "document_registry_path")
    @classmethod
    def resolve_backend_path(cls, value: Path) -> Path:
        """相对路径始终以 backend 为基准，不受启动命令所在目录影响。"""
        return value if value.is_absolute() else BACKEND_DIR / value

    def require_dashscope_api_key(self) -> str:
        """需要调用模型时再检查密钥，避免健康检查被密钥配置影响。"""
        if self.dashscope_api_key is None:
            raise ValueError("未配置 DASHSCOPE_API_KEY")
        return self.dashscope_api_key.get_secret_value()

    def require_database_url(self) -> str:
        """使用会话功能时再检查数据库地址，不影响健康检查和现有问答。"""
        if self.database_url is None:
            raise ValueError("未配置 DATABASE_URL")
        return self.database_url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """全局复用同一份配置，避免每次请求都重复读取环境变量。"""
    return Settings()
