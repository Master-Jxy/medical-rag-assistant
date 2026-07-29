"""新增脱敏模型用量账本。"""

from alembic import op
import sqlalchemy as sa

revision = "0021_model_usage_records"
down_revision = "0020_email_account_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "token_measurement",
                sa.String(20),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.create_check_constraint(
            "ck_agent_runs_token_measurement",
            "token_measurement IN ('actual','unknown','not_applicable')",
        )
    op.create_table(
        "model_usage_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("call_id", sa.String(128), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("surface", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("token_measurement", sa.String(20), nullable=False),
        sa.Column("input_price_snapshot", sa.Numeric(20, 8), nullable=True),
        sa.Column("output_price_snapshot", sa.Numeric(20, 8), nullable=True),
        sa.Column("estimated_cost_cny", sa.Numeric(20, 8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "token_measurement IN ('actual','unknown','not_applicable')",
            name="ck_model_usage_records_measurement",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_model_usage_records_input_tokens",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_model_usage_records_output_tokens",
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_model_usage_records_total_tokens",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("call_id", name="uq_model_usage_records_call_id"),
    )
    op.create_index(
        "ix_model_usage_records_request_id",
        "model_usage_records",
        ["request_id"],
    )
    op.create_index(
        "ix_model_usage_records_user_id",
        "model_usage_records",
        ["user_id"],
    )
    op.create_index(
        "ix_model_usage_records_surface_created",
        "model_usage_records",
        ["surface", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_usage_records_surface_created",
        table_name="model_usage_records",
    )
    op.drop_index(
        "ix_model_usage_records_user_id",
        table_name="model_usage_records",
    )
    op.drop_index(
        "ix_model_usage_records_request_id",
        table_name="model_usage_records",
    )
    op.drop_table("model_usage_records")
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint(
            "ck_agent_runs_token_measurement",
            type_="check",
        )
        batch_op.drop_column("token_measurement")
