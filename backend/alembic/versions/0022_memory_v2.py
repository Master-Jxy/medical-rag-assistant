"""long term memory v2 lifecycle"""
from alembic import op
import sqlalchemy as sa

revision = "0022_memory_v2"
down_revision = "0021_model_usage_records"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_memory_settings") as b:
        b.add_column(sa.Column("auto_extract_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("user_memories") as b:
        b.add_column(sa.Column("category", sa.String(32), nullable=False, server_default="explicit_note"))
        b.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="active"))
        b.add_column(sa.Column("source_type", sa.String(20), nullable=False, server_default="manual"))
        b.add_column(sa.Column("confidence", sa.Float()))
        b.add_column(sa.Column("created_by", sa.String(20), nullable=False, server_default="user"))
        b.add_column(sa.Column("normalized_hash", sa.String(64)))
        b.add_column(sa.Column("valid_until", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("supersedes_id", sa.String(36)))
        b.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True)))
        b.create_foreign_key("fk_user_memory_supersedes", "user_memories", ["supersedes_id"], ["id"], ondelete="SET NULL")
        b.create_unique_constraint("uq_user_memory_normalized_hash", ["user_id", "normalized_hash"])
        b.create_index("ix_user_memories_user_status", ["user_id", "status"])
    op.create_table("user_memory_sources",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("memory_id", sa.String(36), nullable=False),
        sa.Column("surface", sa.String(20), nullable=False), sa.Column("thread_id", sa.String(36)),
        sa.Column("message_id", sa.String(36)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["user_memories.id"], ondelete="CASCADE"))
    op.create_index("ix_user_memory_sources_memory_id", "user_memory_sources", ["memory_id"])
    op.create_table("user_memory_revisions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("memory_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False), sa.Column("label", sa.String(100), nullable=False),
        sa.Column("content", sa.String(1000), nullable=False), sa.Column("category", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("changed_by", sa.String(36), nullable=False),
        sa.Column("change_reason", sa.String(100), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["user_memories.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("memory_id", "version_no", name="uq_memory_revision_version"))
    op.create_index("ix_user_memory_revisions_memory_id", "user_memory_revisions", ["memory_id"])
    op.create_table("memory_extraction_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("surface", sa.String(20), nullable=False), sa.Column("thread_id", sa.String(36), nullable=False),
        sa.Column("through_sequence", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False), sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("usage_group_id", sa.String(36)), sa.Column("error_code", sa.String(64)),
        sa.Column("attempt_count", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("surface", "thread_id", "through_sequence", name="uq_memory_extraction_scope"))
    op.create_index("ix_memory_extraction_runs_user_id", "memory_extraction_runs", ["user_id"])


def downgrade():
    op.drop_table("memory_extraction_runs")
    op.drop_table("user_memory_revisions")
    op.drop_table("user_memory_sources")
    with op.batch_alter_table("user_memories") as b:
        b.drop_index("ix_user_memories_user_status")
        b.drop_constraint("uq_user_memory_normalized_hash", type_="unique")
        b.drop_constraint("fk_user_memory_supersedes", type_="foreignkey")
        for column in ("last_used_at","supersedes_id","valid_until","normalized_hash","created_by","confidence","source_type","status","category"):
            b.drop_column(column)
    with op.batch_alter_table("user_memory_settings") as b:
        b.drop_column("auto_extract_enabled")
