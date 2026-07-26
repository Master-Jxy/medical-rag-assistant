"""add document parse quality details

Revision ID: 0015_parse_quality
Revises: 0014_user_memory
"""

from alembic import op
import sqlalchemy as sa

revision = "0015_parse_quality"
down_revision = "0014_user_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "knowledge_submissions",
        sa.Column("parse_quality", sa.JSON(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE knowledge_submissions "
            "SET parse_quality = :empty_quality "
            "WHERE parse_quality IS NULL"
        ).bindparams(empty_quality="{}")
    )
    with op.batch_alter_table("knowledge_submissions") as batch_op:
        batch_op.alter_column(
            "parse_quality",
            existing_type=sa.JSON(),
            nullable=False,
        )


def downgrade():
    op.drop_column("knowledge_submissions", "parse_quality")
