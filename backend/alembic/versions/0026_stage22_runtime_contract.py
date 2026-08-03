"""add read markers and agent assistant mode"""

from alembic import op
import sqlalchemy as sa


revision = "0026_stage22_runtime_contract"
down_revision = "0025_quota_policy_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "last_read_sequence",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table("agent_threads") as batch_op:
        batch_op.add_column(
            sa.Column(
                "last_read_sequence",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "assistant_mode",
                sa.String(20),
                nullable=False,
                server_default="general",
            )
        )
        batch_op.create_check_constraint(
            "ck_agent_threads_assistant_mode",
            "assistant_mode IN ('general','patient','clinician','knowledge')",
        )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE conversations SET last_read_sequence = COALESCE(("
            "SELECT MAX(messages.sequence) FROM messages "
            "WHERE messages.conversation_id = conversations.id "
            "AND messages.role = 'assistant' "
            "AND messages.status IN ('completed','failed','stopped')"
            "), 0)"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE agent_threads SET last_read_sequence = COALESCE(("
            "SELECT MAX(agent_messages.sequence_no) FROM agent_messages "
            "WHERE agent_messages.thread_id = agent_threads.id "
            "AND agent_messages.role = 'assistant' "
            "AND agent_messages.status IN ('completed','failed','stopped')"
            "), 0)"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("agent_threads") as batch_op:
        batch_op.drop_constraint(
            "ck_agent_threads_assistant_mode",
            type_="check",
        )
        batch_op.drop_column("assistant_mode")
        batch_op.drop_column("last_read_sequence")
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_column("last_read_sequence")
