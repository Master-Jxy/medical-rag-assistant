"""Alembic 测试：验证最新结构、旧会话清理、用户保留和可降级结构。"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.db.session import build_engine
from app.models import Conversation, Message, MessageSource, User
from app.models import KnowledgeDocument
from app.modules.knowledge.migration import import_legacy_registry

BACKEND_DIR = Path(__file__).resolve().parents[1]


def build_alembic_config(database_url: str) -> Config:
    config = Config(BACKEND_DIR / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_all_revision_ids_fit_default_alembic_version_column() -> None:
    config = build_alembic_config("sqlite+pysqlite:///:memory:")
    revisions = ScriptDirectory.from_config(config).walk_revisions()

    assert all(len(revision.revision) <= 32 for revision in revisions)


def test_empty_database_upgrades_to_owned_conversation_schema(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'empty.db'}"
    command.upgrade(build_alembic_config(database_url), "head")

    engine = build_engine(database_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "alembic_version",
        "audit_events",
        "knowledge_submissions",
        "processing_jobs",
        "document_versions",
        "agent_runs",
        "agent_steps",
        "agent_artifacts",
        "agent_threads",
        "agent_messages",
        "answer_feedback",
        "conversation_summaries",
        "user_memory_settings",
        "user_memories",
        "conversations",
        "messages",
        "message_sources",
        "model_usage_records",
        "users",
        "documents",
    } <= tables
    assert "last_read_sequence" in {
        column["name"] for column in inspector.get_columns("conversations")
    }
    assert {"last_read_sequence", "assistant_mode"} <= {
        column["name"] for column in inspector.get_columns("agent_threads")
    }
    assert "parse_quality" in {
        column["name"] for column in inspector.get_columns("knowledge_submissions")
    }
    assert {"document_id", "chunk_id"} <= {
        column["name"] for column in inspector.get_columns("message_sources")
    }
    assert {
        "category",
        "department",
        "expires_at",
        "review_due_at",
        "last_reviewed_at",
        "review_status",
    } <= {
        column["name"] for column in inspector.get_columns("document_versions")
    }
    assert {
        "thread_id",
        "trigger_message_id",
        "response_message_id",
    } <= {
        column["name"] for column in inspector.get_columns("agent_runs")
    }
    assert {
        "thread_id",
        "user_id",
        "role",
        "content",
        "status",
        "run_id",
        "reply_to_message_id",
        "metadata",
    } <= {
        column["name"] for column in inspector.get_columns("agent_messages")
    }

    columns = {column["name"]: column for column in inspector.get_columns("conversations")}
    assert columns["user_id"]["nullable"] is False
    foreign_keys = inspector.get_foreign_keys("conversations")
    assert any(
        foreign_key["constrained_columns"] == ["user_id"]
        and foreign_key["referred_table"] == "users"
        for foreign_key in foreign_keys
    )
    index_names = {index["name"] for index in inspector.get_indexes("conversations")}
    assert "ix_conversations_user_updated_at" in index_names

    document_columns = {
        column["name"]: column for column in inspector.get_columns("documents")
    }
    assert document_columns["uploader_id"]["nullable"] is True
    assert document_columns["is_system"]["nullable"] is False
    assert any(
        foreign_key["constrained_columns"] == ["uploader_id"]
        and foreign_key["referred_table"] == "users"
        for foreign_key in inspector.get_foreign_keys("documents")
    )
    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert user_columns["role"]["nullable"] is False
    assert user_columns["email_verified_at"]["nullable"] is True
    assert user_columns["token_version"]["nullable"] is False
    user_checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints("users")
    }
    assert "super_admin" in user_checks["ck_users_role"]
    audit_columns = {
        column["name"] for column in inspector.get_columns("audit_events")
    }
    assert {
        "actor_user_id",
        "action",
        "object_type",
        "object_id",
        "result",
        "request_id",
        "details",
        "created_at",
    } <= audit_columns


def test_upgrade_clears_unowned_conversations_but_preserves_users(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'existing.db'}"
    config = build_alembic_config(database_url)
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)

    command.upgrade(config, "0001_conversation")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversations (id, title, created_at, updated_at) "
                "VALUES (:id, :title, :created_at, :updated_at)"
            ),
            {
                "id": "legacy-conversation",
                "title": "迁移前测试会话",
                "created_at": now,
                "updated_at": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, sequence, role, content, status, request_id, created_at) "
                "VALUES (:id, :conversation_id, 1, 'assistant', '迁移前消息', "
                "'completed', 'legacy-request', :created_at)"
            ),
            {
                "id": "legacy-message",
                "conversation_id": "legacy-conversation",
                "created_at": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO message_sources "
                "(message_id, position, file_name, page, content) "
                "VALUES ('legacy-message', 1, '旧资料.txt', NULL, '迁移前引用')"
            )
        )

    command.upgrade(config, "0002_users")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, display_name, password_hash, is_active, created_at, updated_at) "
                "VALUES ('preserved-user', 'preserved@example.com', NULL, 'hash', 1, :now, :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(func.count()).select_from(MessageSource)) == 0
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.get(User, "preserved-user") is not None
        assert session.get(User, "preserved-user").role == "user"

    command.downgrade(config, "0002_users")
    assert "user_id" not in {
        column["name"] for column in inspect(engine).get_columns("conversations")
    }
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM users WHERE id = 'preserved-user'")
        ) == 1


def test_super_admin_role_migration_preserves_users_and_has_safe_downgrade(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'roles.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0005_user_role")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, is_active, role, created_at, updated_at) "
                "VALUES ('admin-user', 'admin@example.com', 'hash', 1, 'admin', :now, :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE users SET role = 'super_admin' "
                "WHERE id = 'admin-user'"
            )
        )
        assert connection.scalar(
            text("SELECT role FROM users WHERE id = 'admin-user'")
        ) == "super_admin"

    command.downgrade(config, "0005_user_role")
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT role FROM users WHERE id = 'admin-user'")
        ) == "admin"


def test_email_lifecycle_migration_preserves_users_and_downgrades(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'email-lifecycle.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0019_agent_message_order")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, is_active, role, created_at, updated_at) "
                "VALUES ('legacy-user', 'legacy@example.com', 'hash', 1, 'user', :now, :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT email, email_verified_at, token_version "
                "FROM users WHERE id = 'legacy-user'"
            )
        ).one()
        assert row == ("legacy@example.com", None, 0)

    command.downgrade(config, "0019_agent_message_order")
    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "email_verified_at" not in columns
    assert "token_version" not in columns
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM users WHERE id = 'legacy-user'")
        ) == 1


def test_model_usage_migration_upgrades_and_downgrades_without_touching_users(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'model-usage.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0020_email_account_lifecycle")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, is_active, role, token_version, "
                "created_at, updated_at) VALUES "
                "('usage-user', 'usage@example.com', 'hash', 1, 'user', 0, "
                ":now, :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert "model_usage_records" in inspector.get_table_names()
    assert "token_measurement" in {
        column["name"] for column in inspector.get_columns("agent_runs")
    }
    assert {
        "call_id",
        "request_id",
        "user_id",
        "surface",
        "operation",
        "model_name",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "token_measurement",
        "input_price_snapshot",
        "output_price_snapshot",
        "estimated_cost_cny",
    } <= {
        column["name"]
        for column in inspector.get_columns("model_usage_records")
    }

    command.downgrade(config, "0020_email_account_lifecycle")
    assert "model_usage_records" not in inspect(engine).get_table_names()
    assert "token_measurement" not in {
        column["name"] for column in inspect(engine).get_columns("agent_runs")
    }
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM users WHERE id = 'usage-user'")
        ) == 1


def test_usage_group_migration_recovers_partial_mysql_style_ddl_and_long_call_ids(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'usage-group-recovery.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0022_memory_v2")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)
    long_call_id = "phase16-existing-call-" + ("x" * 90)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO model_usage_records "
                "(id, call_id, request_id, user_id, surface, operation, model_name, "
                "input_tokens, output_tokens, total_tokens, token_measurement, "
                "input_price_snapshot, output_price_snapshot, estimated_cost_cny, "
                "created_at) VALUES "
                "('legacy-usage', :call_id, NULL, NULL, 'rag', 'answer', 'fake', "
                "1, 2, 3, 'actual', NULL, NULL, NULL, :now)"
            ),
            {"call_id": long_call_id, "now": now},
        )
        for ddl in (
            "ALTER TABLE model_usage_records ADD COLUMN usage_group_id VARCHAR(36)",
            "ALTER TABLE model_usage_records ADD COLUMN provider VARCHAR(32) "
            "NOT NULL DEFAULT 'dashscope'",
            "ALTER TABLE model_usage_records ADD COLUMN status VARCHAR(20) "
            "NOT NULL DEFAULT 'completed'",
            "ALTER TABLE model_usage_records ADD COLUMN latency_ms INTEGER",
            "ALTER TABLE model_usage_records ADD COLUMN time_to_first_token_ms INTEGER",
            "ALTER TABLE model_usage_records ADD COLUMN cached_input_tokens INTEGER",
            "ALTER TABLE model_usage_records ADD COLUMN cache_creation_tokens INTEGER",
            "ALTER TABLE model_usage_records ADD COLUMN quota_billable BOOLEAN "
            "NOT NULL DEFAULT 1",
        ):
            connection.execute(text(ddl))

    command.upgrade(config, "head")
    with engine.connect() as connection:
        usage_group_id = connection.scalar(
            text(
                "SELECT usage_group_id FROM model_usage_records "
                "WHERE id = 'legacy-usage'"
            )
        )
        assert usage_group_id is not None
        assert len(usage_group_id) == 36
        assert usage_group_id != long_call_id[:36]


def test_quota_policy_v2_migration_preserves_usage_reservations_and_overrides(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'quota-policy-v2.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0024_user_quota")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)
    current_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    current_end = (
        current_start.replace(year=current_start.year + 1, month=1)
        if current_start.month == 12
        else current_start.replace(month=current_start.month + 1)
    )
    historical_start = current_start - timedelta(days=60)
    historical_end = current_start - timedelta(days=30)

    with engine.begin() as connection:
        for user_id in ("default-user", "assigned-user", "override-user"):
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email, password_hash, is_active, role, token_version, "
                    "created_at, updated_at) VALUES "
                    "(:id, :email, 'hash', 1, 'user', 0, :now, :now)"
                ),
                {
                    "id": user_id,
                    "email": f"{user_id}@example.com",
                    "now": now,
                },
            )
        connection.execute(
            text(
                "INSERT INTO user_quota_assignments "
                "(user_id, plan_id, token_limit_override, request_limit_override, "
                "valid_from, valid_until, updated_by, updated_at) VALUES "
                "('assigned-user', :plan_id, NULL, NULL, :now, NULL, NULL, :now), "
                "('override-user', :plan_id, 250000, 700, :now, NULL, NULL, :now)"
            ),
            {
                "plan_id": "00000000-0000-0000-0000-000000000001",
                "now": now,
            },
        )
        periods = (
            ("period-default", "default-user", current_start, current_end, 100_000),
            ("period-assigned", "assigned-user", current_start, current_end, 100_000),
            ("period-override", "override-user", current_start, current_end, 250_000),
            ("period-history", "default-user", historical_start, historical_end, 100_000),
        )
        for period_id, user_id, start, end, token_limit in periods:
            connection.execute(
                text(
                    "INSERT INTO quota_periods "
                    "(id, user_id, period_start, period_end, token_limit, request_limit, "
                    "used_tokens, reserved_tokens, used_requests, reserved_requests, "
                    "created_at, updated_at) VALUES "
                    "(:id, :user_id, :start, :end, :token_limit, 500, "
                    "12000, 3000, 12, 1, :now, :now)"
                ),
                {
                    "id": period_id,
                    "user_id": user_id,
                    "start": start,
                    "end": end,
                    "token_limit": token_limit,
                    "now": now,
                },
            )
        connection.execute(
            text(
                "INSERT INTO quota_reservations "
                "(id, idempotency_key, user_id, quota_period_id, surface, "
                "usage_group_id, reserved_tokens, charged_tokens, status, "
                "expires_at, created_at, settled_at) VALUES "
                "('reservation', 'migration-reservation', 'default-user', "
                "'period-default', 'rag', 'usage-group', 3000, 0, 'reserved', "
                ":expires_at, :now, NULL)"
            ),
            {"expires_at": now + timedelta(minutes=15), "now": now},
        )

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT token_limit FROM quota_plans WHERE code = 'free'")
        ) == 1_000_000
        rows = dict(connection.execute(
            text("SELECT id, token_limit FROM quota_periods")
        ).all())
        assert rows == {
            "period-default": 1_000_000,
            "period-assigned": 1_000_000,
            "period-override": 250_000,
            "period-history": 100_000,
        }
        assert connection.execute(
            text(
                "SELECT used_tokens, reserved_tokens, used_requests, "
                "reserved_requests FROM quota_periods "
                "WHERE id = 'period-default'"
            )
        ).one() == (12_000, 3_000, 12, 1)
        assert connection.scalar(
            text("SELECT reserved_tokens FROM quota_reservations")
        ) == 3_000
        assert connection.scalar(
            text(
                "SELECT token_limit_override FROM user_quota_assignments "
                "WHERE user_id = 'override-user'"
            )
        ) == 250_000

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE quota_periods SET token_limit = 750000 "
                "WHERE id = 'period-default'"
            )
        )
    command.downgrade(config, "0024_user_quota")
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT token_limit FROM quota_plans WHERE code = 'free'")
        ) == 100_000
        rows = dict(connection.execute(
            text("SELECT id, token_limit FROM quota_periods")
        ).all())
        assert rows == {
            "period-default": 750_000,
            "period-assigned": 100_000,
            "period-override": 250_000,
            "period-history": 100_000,
        }
        assert "policy_migration_version" not in {
            column["name"]
            for column in inspect(engine).get_columns("quota_periods")
        }


def test_stage22_runtime_contract_backfills_read_markers_and_downgrades_safely(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'stage22-runtime.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0025_quota_policy_v2")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, is_active, role, token_version, "
                "created_at, updated_at) VALUES "
                "('stage22-user', 'stage22@example.com', 'hash', 1, 'user', 0, "
                ":now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO conversations "
                "(id, user_id, title, created_at, updated_at) VALUES "
                "('legacy-conversation', 'stage22-user', '旧RAG会话', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO messages "
                "(id, conversation_id, sequence, role, content, status, request_id, created_at) VALUES "
                "('rag-user', 'legacy-conversation', 1, 'user', '问题', 'completed', NULL, :now), "
                "('rag-answer', 'legacy-conversation', 2, 'assistant', '回答', 'completed', NULL, :now), "
                "('rag-pending', 'legacy-conversation', 3, 'assistant', '', 'pending', NULL, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO agent_threads "
                "(id, user_id, title, status, summary, summary_until_message_id, "
                "next_message_sequence, last_message_at, created_at, updated_at) VALUES "
                "('legacy-thread', 'stage22-user', '旧Agent会话', 'active', NULL, NULL, "
                "4, :now, :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO agent_messages "
                "(id, thread_id, user_id, sequence_no, turn_id, role, content, status, "
                "run_id, reply_to_message_id, metadata, created_at, updated_at) VALUES "
                "('agent-user', 'legacy-thread', 'stage22-user', 1, NULL, 'user', "
                "'问题', 'completed', NULL, NULL, '{}', :now, :now), "
                "('agent-answer', 'legacy-thread', 'stage22-user', 2, NULL, 'assistant', "
                "'回答', 'completed', NULL, NULL, '{}', :now, :now), "
                "('agent-pending', 'legacy-thread', 'stage22-user', 3, NULL, 'assistant', "
                "'', 'streaming', NULL, NULL, '{}', :now, :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT last_read_sequence FROM conversations "
                "WHERE id = 'legacy-conversation'"
            )
        ).scalar_one() == 2
        assert connection.execute(
            text(
                "SELECT last_read_sequence, assistant_mode FROM agent_threads "
                "WHERE id = 'legacy-thread'"
            )
        ).one() == (2, "general")

    command.downgrade(config, "0025_quota_policy_v2")
    inspector = inspect(engine)
    assert "last_read_sequence" not in {
        column["name"] for column in inspector.get_columns("conversations")
    }
    assert {"last_read_sequence", "assistant_mode"}.isdisjoint(
        {column["name"] for column in inspector.get_columns("agent_threads")}
    )
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM conversations WHERE id = 'legacy-conversation'")
        ) == 1
        assert connection.scalar(
            text("SELECT COUNT(*) FROM agent_threads WHERE id = 'legacy-thread'")
        ) == 1


def test_stage9_upgrade_registers_legacy_documents_without_duplicate_publication(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'stage9-upgrade.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0007_audit_events")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, is_active, role, created_at, updated_at) "
                "VALUES ('legacy-owner', 'owner@example.com', 'hash', 1, 'user', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO documents "
                "(id, original_name, stored_name, content_hash, size_bytes, chunk_count, "
                "chunk_ids, uploader_id, is_system, status, created_at) VALUES "
                "('system-doc', '系统资料.txt', 'system.txt', :system_hash, 10, 1, "
                " :chunks, NULL, 1, 'ready', :now), "
                "('user-doc', '用户资料.txt', 'user.txt', :user_hash, 10, 1, "
                " :chunks, 'legacy-owner', 0, 'ready', :now)"
            ),
            {
                "system_hash": "a" * 64,
                "user_hash": "b" * 64,
                "chunks": '["chunk-1"]',
                "now": now,
            },
        )

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM knowledge_submissions")
        ) == 2
        assert connection.scalar(text("SELECT COUNT(*) FROM document_versions")) == 2
        assert connection.execute(
            text("SELECT id, status FROM documents ORDER BY id")
        ).all() == [("system-doc", "published"), ("user-doc", "published")]
        assert connection.execute(
            text(
                "SELECT document_id, source, version FROM document_versions "
                "ORDER BY document_id"
            )
        ).all() == [
            ("system-doc", "system", 1),
            ("user-doc", "legacy_upload", 1),
        ]
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM knowledge_submissions "
                "WHERE status = 'published' AND document_id = id"
            )
        ) == 2


def test_upgrade_removes_only_orphaned_published_system_submission(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'orphan-submission.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0010_document_versions")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, is_active, role, created_at, updated_at) "
                "VALUES ('submitter', 'submitter@example.com', 'hash', 1, 'user', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO knowledge_submissions "
                "(id, submitter_id, original_name, stored_name, content_hash, size_bytes, "
                "status, preview_text, preview_pages, parse_warnings, rejection_reason, "
                "failure_reason, document_id, created_at, updated_at) VALUES "
                "('orphan-system', NULL, '已删除系统资料.txt', 'deleted.txt', :system_hash, "
                "10, 'published', NULL, NULL, '[]', NULL, NULL, NULL, :now, :now), "
                "('withdrawn-user', 'submitter', '已撤回资料.txt', 'withdrawn.txt', "
                ":user_hash, 10, 'withdrawn', NULL, NULL, '[]', NULL, NULL, NULL, :now, :now)"
            ),
            {
                "system_hash": "c" * 64,
                "user_hash": "d" * 64,
                "now": now,
            },
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM knowledge_submissions "
                "WHERE id = 'orphan-system'"
            )
        ) == 0
        assert connection.scalar(
            text(
                "SELECT COUNT(*) FROM knowledge_submissions "
                "WHERE id = 'withdrawn-user'"
            )
        ) == 1


def test_agent_thread_migration_preserves_legacy_runs_and_downgrades(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'agent-threads.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "0017_knowledge_governance")
    engine = build_engine(database_url)
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, is_active, role, created_at, updated_at) "
                "VALUES ('legacy-agent-user', 'agent@example.com', 'hash', 1, "
                "'user', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO agent_runs "
                "(id, user_id, task, status, step_count, model_name, max_steps, "
                "max_tokens, max_estimated_cost_cny, used_tokens, estimated_cost_cny, "
                "final_result, error_type, created_at, updated_at, started_at, finished_at) "
                "VALUES ('legacy-run', 'legacy-agent-user', '旧版独立任务', 'completed', "
                "0, 'mock', 5, 12000, 0.05, 0, 0, '完成', NULL, :now, :now, :now, :now)"
            ),
            {"now": now},
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT thread_id, trigger_message_id, response_message_id "
                "FROM agent_runs WHERE id = 'legacy-run'"
            )
        ).one() == (None, None, None)

    command.downgrade(config, "0017_knowledge_governance")
    inspector = inspect(engine)
    assert "agent_threads" not in inspector.get_table_names()
    assert "agent_messages" not in inspector.get_table_names()
    assert {
        column["name"] for column in inspector.get_columns("agent_runs")
    }.isdisjoint(
        {"thread_id", "trigger_message_id", "response_message_id"}
    )
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT COUNT(*) FROM agent_runs WHERE id = 'legacy-run'")
        ) == 1



def test_legacy_json_import_creates_idempotent_system_documents(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'documents.db'}"
    config = build_alembic_config(database_url)
    command.upgrade(config, "head")
    registry_path = tmp_path / "documents.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "document_id": "legacy-document",
                    "file_name": "系统资料.txt",
                    "stored_name": "legacy-document.txt",
                    "file_hash": "a" * 64,
                    "file_size": 128,
                    "chunk_count": 2,
                    "chunk_ids": ["legacy-document:0", "legacy-document:1"],
                    "status": "ready",
                    "created_at": "2026-07-15T00:00:00+00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    engine = build_engine(database_url)
    with Session(engine) as session:
        assert import_legacy_registry(session, registry_path) == 1
        assert import_legacy_registry(session, registry_path) == 0
        saved = session.get(KnowledgeDocument, "legacy-document")
        assert saved is not None
        assert saved.is_system is True
        assert saved.uploader_id is None
        assert saved.chunk_ids == ["legacy-document:0", "legacy-document:1"]

    command.downgrade(config, "0003_conversation_user")
    assert "documents" not in inspect(engine).get_table_names()
