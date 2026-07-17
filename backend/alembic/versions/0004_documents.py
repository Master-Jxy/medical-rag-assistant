"""建立公共知识库文档登记表。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_documents"
down_revision: Union[str, Sequence[str], None] = "0003_conversation_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("chunk_ids", sa.JSON(), nullable=False),
        sa.Column("uploader_id", sa.String(36), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_documents_size_nonnegative"),
        sa.CheckConstraint("chunk_count > 0", name="ck_documents_chunk_count_positive"),
        sa.CheckConstraint("status IN ('ready')", name="ck_documents_status"),
        sa.CheckConstraint(
            "(is_system = 1 AND uploader_id IS NULL) OR "
            "(is_system = 0 AND uploader_id IS NOT NULL)",
            name="ck_documents_owner_kind",
        ),
        sa.ForeignKeyConstraint(
            ["uploader_id"], ["users.id"],
            name="fk_documents_uploader_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash", name="uq_documents_content_hash"),
        sa.UniqueConstraint("stored_name", name="uq_documents_stored_name"),
    )
    op.create_index("ix_documents_created_at", "documents", ["created_at"])
    op.create_index("ix_documents_uploader_id", "documents", ["uploader_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_uploader_id", table_name="documents")
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_table("documents")
