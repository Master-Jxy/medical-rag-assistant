"""add rolling summaries and user-controlled memory

Revision ID: 0014_user_memory
Revises: 0013_answer_feedback
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_user_memory"
down_revision = "0013_answer_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_summaries",
        sa.Column("conversation_id", sa.String(36), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("summarized_through_sequence", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("summarized_through_sequence > 0", name="ck_summary_sequence"),
    )
    op.create_table(
        "user_memory_settings",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("content", sa.String(1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_memories_user_updated", "user_memories", ["user_id", "updated_at"])


def downgrade():
    op.drop_index("ix_user_memories_user_updated", table_name="user_memories")
    op.drop_table("user_memories")
    op.drop_table("user_memory_settings")
    op.drop_table("conversation_summaries")
