"""为用户增加数据库授权角色。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_user_role"
down_revision: Union[str, Sequence[str], None] = "0004_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("role", sa.String(length=20), server_default="user", nullable=False)
        )
        batch_op.create_check_constraint("ck_users_role", "role IN ('user', 'admin')")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role", type_="check")
        batch_op.drop_column("role")
