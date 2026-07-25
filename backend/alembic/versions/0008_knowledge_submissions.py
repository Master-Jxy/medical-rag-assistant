"""增加资料提交状态表并兼容登记现有已发布文档。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_knowledge_submissions"
down_revision: Union[str, Sequence[str], None] = "0007_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("submitter_id", sa.String(36), nullable=True),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("preview_text", sa.Text(), nullable=True),
        sa.Column("preview_pages", sa.Integer(), nullable=True),
        sa.Column("parse_warnings", sa.JSON(), nullable=False),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("failure_reason", sa.String(200), nullable=True),
        sa.Column("document_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_parse','pending_review','rejected','indexing',"
            "'published','failed','withdrawn','archived')",
            name="ck_knowledge_submissions_status",
        ),
        sa.ForeignKeyConstraint(["submitter_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("content_hash", name="uq_knowledge_submissions_hash"),
    )
    op.create_index(
        "ix_knowledge_submissions_submitter_created",
        "knowledge_submissions",
        ["submitter_id", "created_at"],
    )
    op.create_index(
        "ix_knowledge_submissions_status_created",
        "knowledge_submissions",
        ["status", "created_at"],
    )
    op.execute(
        sa.text(
            "INSERT INTO knowledge_submissions "
            "(id, submitter_id, original_name, stored_name, content_hash, size_bytes, "
            "status, preview_text, preview_pages, parse_warnings, rejection_reason, "
            "failure_reason, document_id, created_at, updated_at) "
            "SELECT id, uploader_id, original_name, stored_name, content_hash, size_bytes, "
            "'published', NULL, NULL, '[]', NULL, NULL, id, created_at, created_at "
            "FROM documents"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_submissions_status_created",
        table_name="knowledge_submissions",
    )
    op.drop_index(
        "ix_knowledge_submissions_submitter_created",
        table_name="knowledge_submissions",
    )
    op.drop_table("knowledge_submissions")
