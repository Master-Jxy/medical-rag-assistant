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
    redis_url: SecretStr | None = Field(default=None)
    redis_connect_timeout_seconds: float = Field(default=0.5, gt=0, le=5)
    redis_socket_timeout_seconds: float = Field(default=0.5, gt=0, le=5)
    auth_register_rate_limit: int = Field(default=5, gt=0, le=100)
    auth_register_rate_window_seconds: int = Field(default=600, gt=0, le=86400)
    auth_login_rate_limit: int = Field(default=10, gt=0, le=1000)
    auth_login_rate_window_seconds: int = Field(default=300, gt=0, le=86400)
    chat_rate_limit: int = Field(default=10, gt=0, le=1000)
    chat_rate_window_seconds: int = Field(default=60, gt=0, le=86400)
    upload_rate_limit: int = Field(default=5, gt=0, le=1000)
    upload_rate_window_seconds: int = Field(default=3600, gt=0, le=86400)
    upload_concurrency_limit: int = Field(default=1, gt=0, le=10)
    upload_concurrency_ttl_seconds: int = Field(default=600, gt=0, le=3600)
    generation_lock_ttl_seconds: int = Field(default=600, gt=0, le=3600)
    idempotency_in_progress_ttl_seconds: int = Field(default=600, gt=0, le=3600)
    idempotency_result_ttl_seconds: int = Field(default=86400, gt=0, le=604800)
    auth_rate_limit_fallback_max_keys: int = Field(default=4096, gt=0, le=100000)
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    jwt_secret_key: SecretStr | None = Field(default=None)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=30, gt=0, le=24 * 60)
    chat_model_name: str = "qwen3-max"
    embedding_model_name: str = "text-embedding-v4"
    chroma_persist_dir: Path = BACKEND_DIR / "chroma_db"
    chroma_collection_name: str = "agent"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    document_registry_path: Path = BACKEND_DIR / "data" / "documents.json"
    knowledge_base_version: str = "live_v1"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    chunk_size: int = 800
    chunk_overlap: int = 100
    max_history_rounds: int = 3
    max_history_chars: int = 6000
    rag_min_relevance_score: float | None = Field(default=None, ge=0, le=1)
    rag_filter_department: str | None = None
    rag_filter_topic: str | None = None
    rag_filter_document_type: str | None = None
    rag_filter_knowledge_base_version: str | None = None
    rag_insufficient_knowledge_message: str = (
        "知识库资料不足，无法根据现有资料回答。"
    )
    rag_hybrid_search_enabled: bool = False
    rag_hybrid_vector_weight: float = Field(default=0.7, ge=0, le=1)
    rag_hybrid_keyword_weight: float = Field(default=0.3, ge=0, le=1)
    rag_hybrid_rrf_k: int = Field(default=60, ge=1, le=1000)
    rag_rerank_enabled: bool = False
    rag_rerank_model_name: str = "gte-rerank-v2"
    rag_rerank_max_candidates: int = Field(default=10, ge=1, le=100)
    rag_rerank_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    rag_rerank_max_input_tokens: int = Field(default=12000, ge=1, le=120000)
    rag_rerank_input_price_per_million_tokens_cny: float = Field(
        default=0.8, ge=0, le=1000
    )
    rag_rerank_max_estimated_cost_cny: float = Field(
        default=0.01, ge=0, le=100
    )
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("chroma_persist_dir", "upload_dir", "document_registry_path")
    @classmethod
    def resolve_backend_path(cls, value: Path) -> Path:
        """相对路径始终以 backend 为基准，不受启动命令所在目录影响。"""
        return value if value.is_absolute() else BACKEND_DIR / value

    @field_validator("jwt_algorithm")
    @classmethod
    def allow_supported_jwt_algorithm(cls, value: str) -> str:
        algorithm = value.strip().upper()
        if algorithm != "HS256":
            raise ValueError("JWT_ALGORITHM 当前仅支持 HS256")
        return algorithm

    @field_validator("trusted_proxy_ips")
    @classmethod
    def validate_trusted_proxy_ips(cls, values: list[str]) -> list[str]:
        """代理地址必须显式且合法，避免错误配置后信任任意转发头。"""
        from ipaddress import ip_address

        return [str(ip_address(value.strip())) for value in values]

    @field_validator(
        "rag_filter_department",
        "rag_filter_topic",
        "rag_filter_document_type",
        "rag_filter_knowledge_base_version",
        mode="before",
    )
    @classmethod
    def normalize_optional_rag_filter(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("rag_insufficient_knowledge_message")
    @classmethod
    def validate_rag_insufficient_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 500:
            raise ValueError("RAG知识不足文案必须为1-500个非空字符")
        return cleaned

    @field_validator("rag_rerank_model_name")
    @classmethod
    def validate_rag_rerank_model_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 100:
            raise ValueError("RAG_RERANK_MODEL_NAME 必须为1-100个非空字符")
        return cleaned

    @field_validator("knowledge_base_version")
    @classmethod
    def validate_knowledge_base_version(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 100:
            raise ValueError("KNOWLEDGE_BASE_VERSION 必须为1-100个非空字符")
        return cleaned

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

    def optional_redis_url(self) -> str | None:
        """Redis 是可选基础设施；未配置时现有业务仍可正常运行。"""
        if self.redis_url is None:
            return None
        value = self.redis_url.get_secret_value().strip()
        return value or None

    def require_jwt_secret_key(self) -> str:
        """只在认证接口被调用时检查 JWT 密钥，避免把密钥写进源码。"""
        if self.jwt_secret_key is None:
            raise ValueError("未配置 JWT_SECRET_KEY")
        secret = self.jwt_secret_key.get_secret_value()
        if len(secret) < 32:
            raise ValueError("JWT_SECRET_KEY 长度不能少于 32 个字符")
        return secret


@lru_cache
def get_settings() -> Settings:
    """全局复用同一份配置，避免每次请求都重复读取环境变量。"""
    return Settings()
