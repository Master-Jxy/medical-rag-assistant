"""清理系统文档物理删除后遗留的已发布提交登记。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_cleanup_orphan_system_submissions"
down_revision: Union[str, Sequence[str], None] = "0010_document_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM knowledge_submissions "
            "WHERE status = 'published' "
            "AND submitter_id IS NULL "
            "AND document_id IS NULL"
        )
    )


def downgrade() -> None:
    # 对应系统文档、文件和向量都已被物理删除，不能安全伪造原提交登记。
    pass
