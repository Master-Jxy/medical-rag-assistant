"""清理旧测试会话，并让每个新会话归属于一个用户。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_conversation_user"
down_revision: Union[str, Sequence[str], None] = "0002_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧会话没有可靠的用户归属，按已确认的产品决策在迁移前备份、迁移时清空。
    op.execute(sa.text("DELETE FROM message_sources"))
    op.execute(sa.text("DELETE FROM messages"))
    op.execute(sa.text("DELETE FROM conversations"))

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=False))
        batch_op.create_index("ix_conversations_user_id", ["user_id"])
        batch_op.create_index(
            "ix_conversations_user_updated_at", ["user_id", "updated_at"]
        )
        batch_op.create_foreign_key(
            "fk_conversations_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    # 降级只恢复旧结构；已清理的测试会话需要从迁移前备份恢复。
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_constraint("fk_conversations_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_conversations_user_updated_at")
        batch_op.drop_index("ix_conversations_user_id")
        batch_op.drop_column("user_id")
