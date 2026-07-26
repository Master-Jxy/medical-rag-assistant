"""建立Agent会话内确定消息顺序。"""

from collections import defaultdict

from alembic import op
import sqlalchemy as sa

revision = "0019_agent_message_order"
down_revision = "0018_agent_threads_messages"
branch_labels = None
depends_on = None


def _backfill(connection) -> None:
    messages = list(
        connection.execute(
            sa.text(
                """
                SELECT id, thread_id, role, created_at
                FROM agent_messages
                ORDER BY thread_id, created_at, id
                """
            )
        ).mappings()
    )
    runs = list(
        connection.execute(
            sa.text(
                """
                SELECT id, thread_id, trigger_message_id, response_message_id,
                       created_at
                FROM agent_runs
                WHERE thread_id IS NOT NULL
                """
            )
        ).mappings()
    )
    by_thread: dict[str, list[dict]] = defaultdict(list)
    for message in messages:
        by_thread[message["thread_id"]].append(dict(message))
    runs_by_thread: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        runs_by_thread[run["thread_id"]].append(dict(run))

    for thread_id, thread_messages in by_thread.items():
        message_by_id = {item["id"]: item for item in thread_messages}
        assigned: set[str] = set()
        units: list[tuple[object, str, list[tuple[str, str | None]]]] = []
        for run in runs_by_thread.get(thread_id, []):
            pair = []
            trigger = message_by_id.get(run["trigger_message_id"])
            response = message_by_id.get(run["response_message_id"])
            if trigger is not None:
                pair.append((trigger["id"], run["id"]))
            if response is not None:
                pair.append((response["id"], run["id"]))
            if not pair:
                continue
            assigned.update(message_id for message_id, _ in pair)
            first = trigger or response
            units.append((first["created_at"], first["id"], pair))
        for message in thread_messages:
            if message["id"] not in assigned:
                units.append(
                    (
                        message["created_at"],
                        message["id"],
                        [(message["id"], None)],
                    )
                )
        units.sort(key=lambda item: (item[0], item[1]))
        sequence = 1
        for _, _, unit_messages in units:
            for message_id, turn_id in unit_messages:
                connection.execute(
                    sa.text(
                        """
                        UPDATE agent_messages
                        SET sequence_no = :sequence_no, turn_id = :turn_id
                        WHERE id = :message_id
                        """
                    ),
                    {
                        "sequence_no": sequence,
                        "turn_id": turn_id,
                        "message_id": message_id,
                    },
                )
                sequence += 1
        connection.execute(
            sa.text(
                """
                UPDATE agent_threads
                SET next_message_sequence = :next_sequence
                WHERE id = :thread_id
                """
            ),
            {"next_sequence": sequence, "thread_id": thread_id},
        )


def upgrade() -> None:
    with op.batch_alter_table("agent_threads") as batch_op:
        batch_op.add_column(
            sa.Column(
                "next_message_sequence",
                sa.BigInteger(),
                nullable=False,
                server_default="1",
            )
        )
    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.add_column(
            sa.Column("sequence_no", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(sa.Column("turn_id", sa.String(36), nullable=True))

    _backfill(op.get_bind())

    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.alter_column(
            "sequence_no",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch_op.create_unique_constraint(
            "uq_agent_messages_thread_sequence",
            ["thread_id", "sequence_no"],
        )
        batch_op.create_index(
            "ix_agent_messages_thread_sequence",
            ["thread_id", "sequence_no"],
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_messages") as batch_op:
        batch_op.drop_index("ix_agent_messages_thread_sequence")
        batch_op.drop_constraint(
            "uq_agent_messages_thread_sequence",
            type_="unique",
        )
        batch_op.drop_column("turn_id")
        batch_op.drop_column("sequence_no")
    with op.batch_alter_table("agent_threads") as batch_op:
        batch_op.drop_column("next_message_sequence")
