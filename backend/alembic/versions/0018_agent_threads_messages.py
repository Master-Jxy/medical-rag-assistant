"""增加Agent会话、消息及运行关联。"""

from alembic import op
import sqlalchemy as sa

revision = "0018_agent_threads_messages"
down_revision = "0017_knowledge_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_threads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_until_message_id", sa.String(36), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','archived')",
            name="ck_agent_threads_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_agent_threads_user_id_users",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_agent_threads_user_status_last_message",
        "agent_threads",
        ["user_id", "status", "last_message_at"],
    )
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("thread_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("reply_to_message_id", sa.String(36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('user','assistant','system')",
            name="ck_agent_messages_role",
        ),
        sa.CheckConstraint(
            "status IN ('pending','streaming','completed','failed','stopped')",
            name="ck_agent_messages_status",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["agent_threads.id"],
            name="fk_agent_messages_thread_id_threads",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_agent_messages_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name="fk_agent_messages_run_id_runs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reply_to_message_id"],
            ["agent_messages.id"],
            name="fk_agent_messages_reply_to_messages",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("run_id", name="uq_agent_messages_run_id"),
    )
    op.create_index(
        "ix_agent_messages_thread_created",
        "agent_messages",
        ["thread_id", "created_at"],
    )
    op.create_index(
        "ix_agent_messages_user_created",
        "agent_messages",
        ["user_id", "created_at"],
    )
    with op.batch_alter_table("agent_threads") as batch_op:
        batch_op.create_foreign_key(
            "fk_agent_threads_summary_message",
            "agent_messages",
            ["summary_until_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(sa.Column("thread_id", sa.String(36), nullable=True))
        batch_op.add_column(
            sa.Column("trigger_message_id", sa.String(36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("response_message_id", sa.String(36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_agent_runs_thread_id_threads",
            "agent_threads",
            ["thread_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_agent_runs_trigger_message",
            "agent_messages",
            ["trigger_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_agent_runs_response_message",
            "agent_messages",
            ["response_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_agent_runs_trigger_message_id",
            ["trigger_message_id"],
        )
        batch_op.create_unique_constraint(
            "uq_agent_runs_response_message_id",
            ["response_message_id"],
        )
        batch_op.create_index(
            "ix_agent_runs_thread_created",
            ["thread_id", "created_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_index("ix_agent_runs_thread_created")
        batch_op.drop_constraint(
            "uq_agent_runs_response_message_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "uq_agent_runs_trigger_message_id",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_agent_runs_response_message",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_agent_runs_trigger_message",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_agent_runs_thread_id_threads",
            type_="foreignkey",
        )
        batch_op.drop_column("response_message_id")
        batch_op.drop_column("trigger_message_id")
        batch_op.drop_column("thread_id")
    with op.batch_alter_table("agent_threads") as batch_op:
        batch_op.drop_constraint(
            "fk_agent_threads_summary_message",
            type_="foreignkey",
        )
    op.drop_index(
        "ix_agent_messages_user_created",
        table_name="agent_messages",
    )
    op.drop_index(
        "ix_agent_messages_thread_created",
        table_name="agent_messages",
    )
    op.drop_table("agent_messages")
    op.drop_index(
        "ix_agent_threads_user_status_last_message",
        table_name="agent_threads",
    )
    op.drop_table("agent_threads")
