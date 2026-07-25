"""增加安全审计事件表。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_audit_events"
down_revision: Union[str, Sequence[str], None] = "0006_super_admin_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("object_type", sa.String(length=50), nullable=False),
        sa.Column("object_id", sa.String(length=100), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_created_at",
        "audit_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_actor_created",
        "audit_events",
        ["actor_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_object",
        "audit_events",
        ["object_type", "object_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_object", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_created", table_name="audit_events")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_table("audit_events")
