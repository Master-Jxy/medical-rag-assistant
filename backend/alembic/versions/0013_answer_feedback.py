"""add answer feedback and human review queue

Revision ID: 0013_answer_feedback
Revises: 0012_agent_persistence
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_answer_feedback"
down_revision = "0012_agent_persistence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "answer_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("rating", sa.String(10), nullable=False),
        sa.Column("question_category", sa.String(30), nullable=False),
        sa.Column("issue_category", sa.String(30)),
        sa.Column("comment", sa.String(500)),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("reviewer_id", sa.String(36)),
        sa.Column("review_note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("message_id", name="uq_answer_feedback_message"),
        sa.CheckConstraint("rating IN ('up','down')", name="ck_feedback_rating"),
        sa.CheckConstraint(
            "question_category IN ('symptom','medication','test','emergency',"
            "'prevention','general')",
            name="ck_feedback_question_category",
        ),
        sa.CheckConstraint(
            "issue_category IS NULL OR issue_category IN "
            "('inaccurate','irrelevant','incomplete','unsafe','citation','other')",
            name="ck_feedback_issue_category",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','resolved','dismissed')",
            name="ck_feedback_review_status",
        ),
    )
    op.create_index("ix_feedback_user_updated", "answer_feedback", ["user_id", "updated_at"])
    op.create_index("ix_feedback_review_created", "answer_feedback", ["review_status", "created_at"])
    op.create_index("ix_feedback_categories", "answer_feedback", ["question_category", "issue_category"])


def downgrade():
    op.drop_index("ix_feedback_categories", table_name="answer_feedback")
    op.drop_index("ix_feedback_review_created", table_name="answer_feedback")
    op.drop_index("ix_feedback_user_updated", table_name="answer_feedback")
    op.drop_table("answer_feedback")
