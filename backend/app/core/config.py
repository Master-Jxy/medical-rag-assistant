"""集中读取后端配置，真实 API Key 只来自环境变量或本地 .env。"""

from functools import lru_cache
from pathlib import Path

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    generation_active_run_limit: int = Field(default=2, ge=1, le=4)
    generation_lock_cleanup_grace_seconds: int = Field(default=30, ge=1, le=300)
    rag_pending_recovery_age_seconds: int = Field(default=900, ge=60, le=86400)
    idempotency_in_progress_ttl_seconds: int = Field(default=600, gt=0, le=3600)
    idempotency_result_ttl_seconds: int = Field(default=86400, gt=0, le=604800)
    auth_rate_limit_fallback_max_keys: int = Field(default=4096, gt=0, le=100000)
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    jwt_secret_key: SecretStr | None = Field(default=None)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=30, gt=0, le=24 * 60)
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_ssl: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    mail_from_name: str = "医疗知识库助手"
    email_code_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    email_code_resend_seconds: int = Field(default=60, ge=1, le=600)
    email_code_max_attempts: int = Field(default=5, ge=1, le=10)
    chat_model_name: str = "qwen3-max"
    chat_input_price_per_million_tokens_cny: float | None = Field(
        default=None, ge=0, le=1000
    )
    chat_output_price_per_million_tokens_cny: float | None = Field(
        default=None, ge=0, le=1000
    )
    memory_auto_extraction_enabled: bool = False
    memory_extraction_interval_turns: int = Field(default=3, ge=1, le=20)
    memory_rag_max_items: int = Field(default=4, ge=1, le=20)
    memory_agent_max_items: int = Field(default=6, ge=1, le=20)
    quota_policy_mode: Literal["off", "shadow", "enforce"] | None = None
    quota_enforcement_enabled: bool = False
    default_quota_plan_code: str = "free"
    quota_rag_reserve_tokens: int = Field(default=4000, ge=1, le=200000)
    quota_agent_reserve_tokens: int = Field(default=12000, ge=1, le=200000)
    quota_rag_max_output_tokens: int = Field(default=2000, ge=100, le=10000)
    quota_rag_source_wrapper_tokens: int = Field(default=200, ge=0, le=5000)
    embedding_model_name: str = "text-embedding-v4"
    dashscope_max_retries: int = Field(default=2, ge=0, le=10)
    chroma_persist_dir: Path = BACKEND_DIR / "chroma_db"
    chroma_collection_name: str = "agent"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    submission_dir: Path = BACKEND_DIR / "data" / "submissions"
    document_registry_path: Path = BACKEND_DIR / "data" / "documents.json"
    knowledge_base_version: str = "live_v1"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    docling_pdf_candidate_enabled: bool = False
    docling_pdf_candidate_promoted: bool = False
    docling_pdf_max_pages: int = Field(default=20, ge=1, le=50)
    docling_pdf_max_file_size_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1, le=10 * 1024 * 1024
    )
    docling_pdf_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    web_snapshot_fetch_enabled: bool = False
    web_snapshot_allowed_hosts: list[str] = Field(default_factory=list)
    web_snapshot_max_bytes: int = Field(default=3 * 1024 * 1024, gt=0, le=5 * 1024 * 1024)
    web_snapshot_max_redirects: int = Field(default=3, ge=0, le=3)
    web_snapshot_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    web_snapshot_read_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    web_snapshot_total_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
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
    telemetry_enabled: bool = True
    telemetry_log_path: Path = BACKEND_DIR / "logs" / "telemetry.jsonl"
    telemetry_log_max_bytes: int = Field(
        default=5 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024
    )
    telemetry_log_backup_count: int = Field(default=5, ge=1, le=30)
    agent_enabled: bool = False
    agent_max_steps: int = Field(default=5, ge=1, le=5)
    agent_max_tool_calls: int = Field(default=3, ge=1, le=3)
    agent_max_model_calls: int = Field(default=4, ge=1, le=4)
    agent_max_specialists: int = Field(default=2, ge=1, le=2)
    agent_max_handoffs: int = Field(default=1, ge=0, le=1)
    agent_tool_timeout_seconds: float = Field(default=30.0, gt=0, le=60)
    agent_run_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    agent_max_tokens: int = Field(default=12_000, ge=1, le=200_000)
    agent_max_estimated_cost_cny: float = Field(default=0.05, ge=0, le=10)
    agent_input_price_per_million_tokens_cny: float = Field(
        default=2.5, ge=0, le=1000
    )
    agent_output_price_per_million_tokens_cny: float = Field(
        default=10.0, ge=0, le=1000
    )
    agent_model_max_output_tokens: int = Field(default=1200, ge=100, le=4000)
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator(
        "chroma_persist_dir",
        "upload_dir",
        "submission_dir",
        "document_registry_path",
        "telemetry_log_path",
    )
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

    @field_validator("web_snapshot_allowed_hosts", mode="before")
    @classmethod
    def normalize_web_snapshot_allowed_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("smtp_host", "mail_from_name")
    @classmethod
    def validate_non_empty_mail_setting(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("邮件主机和发件人名称不能为空")
        return cleaned

    @field_validator("smtp_username", mode="before")
    @classmethod
    def normalize_optional_smtp_username(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator(
        "chat_input_price_per_million_tokens_cny",
        "chat_output_price_per_million_tokens_cny",
        mode="before",
    )
    @classmethod
    def normalize_optional_chat_price(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("quota_policy_mode", mode="before")
    @classmethod
    def normalize_optional_quota_policy_mode(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip().lower()
            return cleaned or None
        return value

    @model_validator(mode="after")
    def validate_generation_lock_lifetime(self):
        minimum = (
            self.agent_run_timeout_seconds
            + self.generation_lock_cleanup_grace_seconds
        )
        if self.generation_lock_ttl_seconds <= minimum:
            raise ValueError(
                "GENERATION_LOCK_TTL_SECONDS 必须大于 "
                "AGENT_RUN_TIMEOUT_SECONDS 与收尾余量之和"
            )
        if self.rag_pending_recovery_age_seconds <= (
            self.generation_lock_ttl_seconds
            + self.generation_lock_cleanup_grace_seconds
        ):
            raise ValueError(
                "RAG_PENDING_RECOVERY_AGE_SECONDS 必须大于生成锁 TTL 与收尾余量之和"
            )
        return self

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

    def require_smtp_credentials(self) -> tuple[str, str]:
        """真实邮件发送时才读取凭据，健康检查和Fake测试不依赖授权码。"""
        if self.smtp_username is None or self.smtp_password is None:
            raise ValueError("未配置 SMTP_USERNAME 或 SMTP_PASSWORD")
        password = self.smtp_password.get_secret_value().strip()
        if not password:
            raise ValueError("SMTP_PASSWORD 不能为空")
        return self.smtp_username, password


@lru_cache
def get_settings() -> Settings:
    """全局复用同一份配置，避免每次请求都重复读取环境变量。"""
    return Settings()
