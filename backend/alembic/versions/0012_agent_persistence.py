"""增加按用户隔离的Agent运行、步骤和产物。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_agent_persistence"
down_revision: Union[str, Sequence[str], None] = "0011_orphan_submission_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=True),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("max_estimated_cost_cny", sa.Float(), nullable=False),
        sa.Column("used_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_cny", sa.Float(), nullable=False),
        sa.Column("final_result", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','stopped')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint(
            "step_count >= 0 AND step_count <= max_steps",
            name="ck_agent_runs_step_count",
        ),
        sa.CheckConstraint(
            "max_steps >= 1 AND max_steps <= 5",
            name="ck_agent_runs_max_steps",
        ),
        sa.CheckConstraint(
            "max_tokens > 0 AND used_tokens >= 0",
            name="ck_agent_runs_tokens",
        ),
        sa.CheckConstraint(
            "max_estimated_cost_cny >= 0 AND estimated_cost_cny >= 0",
            name="ck_agent_runs_cost",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_agent_runs_user_created",
        "agent_runs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_agent_runs_user_status",
        "agent_runs",
        ["user_id", "status"],
    )
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_name", sa.String(50), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','stopped')",
            name="ck_agent_steps_status",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_agent_steps_sequence"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_agent_steps_duration",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_steps_run_sequence"),
    )
    op.create_index(
        "ix_agent_steps_run_created",
        "agent_steps",
        ["run_id", "created_at"],
    )
    op.create_table(
        "agent_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_agent_artifacts_run_created",
        "agent_artifacts",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_artifacts_run_created", table_name="agent_artifacts")
    op.drop_table("agent_artifacts")
    op.drop_index("ix_agent_steps_run_created", table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index("ix_agent_runs_user_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_created", table_name="agent_runs")
    op.drop_table("agent_runs")
