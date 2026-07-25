"""增加持久化处理任务表。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_processing_jobs"
down_revision: Union[str, Sequence[str], None] = "0008_knowledge_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("object_type", sa.String(50), nullable=False),
        sa.Column("object_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_processing_jobs_status",
        ),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_jobs_progress",
        ),
    )
    op.create_index(
        "ix_processing_jobs_status_created",
        "processing_jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_processing_jobs_object",
        "processing_jobs",
        ["object_type", "object_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_object", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_status_created", table_name="processing_jobs")
    op.drop_table("processing_jobs")
