"""answer-level usage grouping and timing"""
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = "0023_usage_groups"
down_revision = "0022_memory_v2"
branch_labels = None
depends_on = None


USAGE_COLUMNS = (
    sa.Column("usage_group_id", sa.String(36)),
    sa.Column("provider", sa.String(32), nullable=False, server_default="dashscope"),
    sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
    sa.Column("latency_ms", sa.Integer()),
    sa.Column("time_to_first_token_ms", sa.Integer()),
    sa.Column("cached_input_tokens", sa.Integer()),
    sa.Column("cache_creation_tokens", sa.Integer()),
    sa.Column("quota_billable", sa.Boolean(), nullable=False, server_default=sa.true()),
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"]
        for column in inspector.get_columns("model_usage_records")
    }
    with op.batch_alter_table("model_usage_records") as b:
        for column in USAGE_COLUMNS:
            if column.name not in existing_columns:
                b.add_column(column)

    inspector = sa.inspect(bind)
    existing_indexes = {
        index["name"]
        for index in inspector.get_indexes("model_usage_records")
    }
    if "ix_model_usage_records_usage_group_id" not in existing_indexes:
        op.create_index(
            "ix_model_usage_records_usage_group_id",
            "model_usage_records",
            ["usage_group_id"],
        )

    rows = bind.execute(
        sa.text(
            "SELECT id, call_id FROM model_usage_records "
            "WHERE usage_group_id IS NULL"
        )
    ).all()
    for record_id, call_id in rows:
        usage_group_id = str(uuid5(NAMESPACE_URL, f"model-usage:{call_id}"))
        bind.execute(
            sa.text(
                "UPDATE model_usage_records "
                "SET usage_group_id = :usage_group_id WHERE id = :record_id"
            ),
            {"usage_group_id": usage_group_id, "record_id": record_id},
        )

def downgrade():
    with op.batch_alter_table("model_usage_records") as b:
        b.drop_index("ix_model_usage_records_usage_group_id")
        for c in ("quota_billable","cache_creation_tokens","cached_input_tokens","time_to_first_token_ms","latency_ms","status","provider","usage_group_id"):
            b.drop_column(c)
