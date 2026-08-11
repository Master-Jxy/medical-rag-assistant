"""upgrade processing jobs to a leased MySQL queue"""

from alembic import op
import sqlalchemy as sa


revision = "0033_stage26_job_leases"
down_revision = "0032_stage26_vision_ocr_routes"
branch_labels = None
depends_on = None


NEW_STATUS_CONSTRAINT = (
    "status IN ('queued','running','retry_wait','completed','failed','cancelled')"
)
OLD_STATUS_CONSTRAINT = (
    "status IN ('queued','running','completed','failed','cancelled')"
)


def upgrade() -> None:
    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.drop_index("ix_processing_jobs_status_created")
        batch_op.drop_constraint("ck_processing_jobs_status", type_="check")
        batch_op.add_column(sa.Column("dispatch_key", sa.String(191), nullable=True))
        batch_op.add_column(sa.Column("payload", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("lease_owner", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_error_code", sa.String(100), nullable=True))

    op.execute("UPDATE processing_jobs SET dispatch_key = id WHERE dispatch_key IS NULL")
    op.execute("UPDATE processing_jobs SET available_at = created_at WHERE available_at IS NULL")
    op.execute("UPDATE processing_jobs SET max_attempts = 3 WHERE max_attempts IS NULL")

    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.alter_column("dispatch_key", existing_type=sa.String(191), nullable=False)
        batch_op.alter_column("available_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch_op.alter_column("max_attempts", existing_type=sa.Integer(), nullable=False)
        batch_op.create_check_constraint("ck_processing_jobs_status", NEW_STATUS_CONSTRAINT)
        batch_op.create_check_constraint("ck_jobs_attempt_count", "attempt_count >= 0")
        batch_op.create_check_constraint("ck_jobs_max_attempts", "max_attempts > 0")
        batch_op.create_index("uq_processing_jobs_dispatch_key", ["dispatch_key"], unique=True)
        batch_op.create_index("ix_processing_jobs_status_available", ["status", "available_at"])
        batch_op.create_index("ix_processing_jobs_lease", ["status", "lease_expires_at"])


def downgrade() -> None:
    op.execute("UPDATE processing_jobs SET status = 'queued' WHERE status = 'retry_wait'")
    with op.batch_alter_table("processing_jobs") as batch_op:
        batch_op.drop_index("ix_processing_jobs_lease")
        batch_op.drop_index("ix_processing_jobs_status_available")
        batch_op.drop_index("uq_processing_jobs_dispatch_key")
        batch_op.drop_constraint("ck_jobs_max_attempts", type_="check")
        batch_op.drop_constraint("ck_jobs_attempt_count", type_="check")
        batch_op.drop_constraint("ck_processing_jobs_status", type_="check")
        batch_op.create_check_constraint("ck_processing_jobs_status", OLD_STATUS_CONSTRAINT)
        batch_op.create_index("ix_processing_jobs_status_created", ["status", "created_at"])
        batch_op.drop_column("last_error_code")
        batch_op.drop_column("cancel_requested_at")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("lease_owner")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("available_at")
        batch_op.drop_column("payload")
        batch_op.drop_column("dispatch_key")
