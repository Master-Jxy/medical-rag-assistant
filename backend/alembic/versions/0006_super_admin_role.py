"""扩展用户角色约束以支持超级管理员。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_super_admin_role"
down_revision: Union[str, Sequence[str], None] = "0005_user_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role", type_="check")
        batch_op.create_check_constraint(
            "ck_users_role",
            "role IN ('user', 'admin', 'super_admin')",
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET role = 'admin' "
            "WHERE role = 'super_admin'"
        )
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role", type_="check")
        batch_op.create_check_constraint(
            "ck_users_role",
            "role IN ('user', 'admin')",
        )
