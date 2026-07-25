"""增加知识资产版本元数据并规范发布状态。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_document_versions"
down_revision: Union[str, Sequence[str], None] = "0009_processing_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_constraint("ck_documents_status", type_="check")
        batch_op.create_check_constraint(
            "ck_documents_status",
            "status IN ('ready','published','archived','failed')",
        )
    op.execute(sa.text("UPDATE documents SET status = 'published' WHERE status = 'ready'"))
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("replaces_document_id", sa.String(36), nullable=True),
        sa.Column("source", sa.String(255), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_document_versions_positive"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["replaces_document_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index(
        "ix_document_versions_replaces",
        "document_versions",
        ["replaces_document_id"],
    )
    op.execute(
        sa.text(
            "INSERT INTO document_versions "
            "(id, document_id, version, replaces_document_id, source, tags, created_at) "
            "SELECT id, id, 1, NULL, "
            "CASE WHEN is_system = 1 THEN 'system' ELSE 'legacy_upload' END, "
            "'[]', created_at FROM documents"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_document_versions_replaces", table_name="document_versions")
    op.drop_table("document_versions")
    op.execute(sa.text("UPDATE documents SET status = 'ready'"))
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_constraint("ck_documents_status", type_="check")
        batch_op.create_check_constraint("ck_documents_status", "status IN ('ready')")
