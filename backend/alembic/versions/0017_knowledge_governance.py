"""add knowledge taxonomy expiry and review governance

Revision ID: 0017_knowledge_governance
Revises: 0016_citation_trace
"""

from alembic import op
import sqlalchemy as sa

revision = "0017_knowledge_governance"
down_revision = "0016_citation_trace"
branch_labels = None
depends_on = None


def upgrade():
    for name, column in (
        ("category", sa.Column("category", sa.String(100))),
        ("department", sa.Column("department", sa.String(100))),
        ("expires_at", sa.Column("expires_at", sa.DateTime(timezone=True))),
        ("review_due_at", sa.Column("review_due_at", sa.DateTime(timezone=True))),
        ("last_reviewed_at", sa.Column("last_reviewed_at", sa.DateTime(timezone=True))),
        ("review_status", sa.Column("review_status", sa.String(20), nullable=False, server_default="current")),
    ):
        op.add_column("document_versions", column)
    op.create_index("ix_document_versions_governance", "document_versions", ["review_status", "review_due_at"])
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.create_check_constraint(
            "ck_document_versions_review_status",
            "review_status IN ('current','due','in_review')",
        )


def downgrade():
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_constraint(
            "ck_document_versions_review_status", type_="check"
        )
    op.drop_index("ix_document_versions_governance", table_name="document_versions")
    for name in ("review_status", "last_reviewed_at", "review_due_at", "expires_at", "department", "category"):
        op.drop_column("document_versions", name)
