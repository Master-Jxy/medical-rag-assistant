"""add web snapshot metadata to submissions"""

from alembic import op
import sqlalchemy as sa


revision = "0027_web_snapshot_submissions"
down_revision = "0026_stage22_runtime_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_submissions") as batch_op:
        batch_op.add_column(sa.Column("snapshot_original_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("snapshot_final_url", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("snapshot_fetched_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("snapshot_response_mime", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("snapshot_content_sha256", sa.String(length=64), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_submissions") as batch_op:
        batch_op.drop_column("snapshot_content_sha256")
        batch_op.drop_column("snapshot_response_mime")
        batch_op.drop_column("snapshot_fetched_at")
        batch_op.drop_column("snapshot_final_url")
        batch_op.drop_column("snapshot_original_url")
