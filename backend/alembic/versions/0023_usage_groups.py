"""answer-level usage grouping and timing"""
from alembic import op
import sqlalchemy as sa

revision = "0023_usage_groups"
down_revision = "0022_memory_v2"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("model_usage_records") as b:
        b.add_column(sa.Column("usage_group_id", sa.String(36)))
        b.add_column(sa.Column("provider", sa.String(32), nullable=False, server_default="dashscope"))
        b.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="completed"))
        b.add_column(sa.Column("latency_ms", sa.Integer()))
        b.add_column(sa.Column("time_to_first_token_ms", sa.Integer()))
        b.add_column(sa.Column("cached_input_tokens", sa.Integer()))
        b.add_column(sa.Column("cache_creation_tokens", sa.Integer()))
        b.add_column(sa.Column("quota_billable", sa.Boolean(), nullable=False, server_default=sa.true()))
        b.create_index("ix_model_usage_records_usage_group_id", ["usage_group_id"])
    op.execute("UPDATE model_usage_records SET usage_group_id = call_id WHERE usage_group_id IS NULL")

def downgrade():
    with op.batch_alter_table("model_usage_records") as b:
        b.drop_index("ix_model_usage_records_usage_group_id")
        for c in ("quota_billable","cache_creation_tokens","cached_input_tokens","time_to_first_token_ms","latency_ms","status","provider","usage_group_id"):
            b.drop_column(c)
