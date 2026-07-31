"""raise the default quota while preserving usage and manual overrides"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0025_quota_policy_v2"
down_revision = "0024_user_quota"
branch_labels = None
depends_on = None

OLD_TOKEN_LIMIT = 100_000
NEW_TOKEN_LIMIT = 1_000_000
MIGRATION_MARK = revision


def _column_names(bind) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns("quota_periods")
    }


def _table_column_names(bind, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns(table_name)
    }


def upgrade() -> None:
    bind = op.get_bind()
    if "policy_migration_version" not in _column_names(bind):
        with op.batch_alter_table("quota_periods") as batch_op:
            batch_op.add_column(
                sa.Column("policy_migration_version", sa.String(32))
            )

    if "quota_policy_events" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "quota_policy_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("surface", sa.String(20), nullable=False),
            sa.Column("policy_mode", sa.String(20), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("requested_tokens", sa.Integer(), nullable=False),
            sa.Column("remaining_tokens", sa.Integer(), nullable=False),
            sa.Column("remaining_requests", sa.Integer(), nullable=False),
            sa.Column("requested_estimated_cost_cny", sa.Numeric(20, 8)),
            sa.Column("remaining_estimated_cost_cny", sa.Numeric(20, 8)),
            sa.Column("would_block", sa.Boolean(), nullable=False),
            sa.Column("reason_code", sa.String(64)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "idempotency_key",
                name="uq_quota_policy_event_idempotency",
            ),
        )
        op.create_index(
            "ix_quota_policy_events_user_created",
            "quota_policy_events",
            ["user_id", "created_at"],
        )
    else:
        event_columns = _table_column_names(bind, "quota_policy_events")
        with op.batch_alter_table("quota_policy_events") as batch_op:
            if "requested_estimated_cost_cny" not in event_columns:
                batch_op.add_column(
                    sa.Column("requested_estimated_cost_cny", sa.Numeric(20, 8))
                )
            if "remaining_estimated_cost_cny" not in event_columns:
                batch_op.add_column(
                    sa.Column("remaining_estimated_cost_cny", sa.Numeric(20, 8))
                )

    assignment_columns = _table_column_names(bind, "user_quota_assignments")
    if "estimated_cost_limit_cny_override" not in assignment_columns:
        with op.batch_alter_table("user_quota_assignments") as batch_op:
            batch_op.add_column(
                sa.Column("estimated_cost_limit_cny_override", sa.Numeric(20, 8))
            )

    period_columns = _table_column_names(bind, "quota_periods")
    with op.batch_alter_table("quota_periods") as batch_op:
        if "estimated_cost_limit_cny" not in period_columns:
            batch_op.add_column(sa.Column("estimated_cost_limit_cny", sa.Numeric(20, 8)))
        if "used_estimated_cost_cny" not in period_columns:
            batch_op.add_column(
                sa.Column(
                    "used_estimated_cost_cny",
                    sa.Numeric(20, 8),
                    nullable=False,
                    server_default="0",
                )
            )
        if "reserved_estimated_cost_cny" not in period_columns:
            batch_op.add_column(
                sa.Column(
                    "reserved_estimated_cost_cny",
                    sa.Numeric(20, 8),
                    nullable=False,
                    server_default="0",
                )
            )

    reservation_columns = _table_column_names(bind, "quota_reservations")
    with op.batch_alter_table("quota_reservations") as batch_op:
        for name, column_type in (
            ("reserved_input_tokens", sa.Integer()),
            ("reserved_output_tokens", sa.Integer()),
            ("input_price_snapshot", sa.Numeric(20, 8)),
            ("output_price_snapshot", sa.Numeric(20, 8)),
            ("reserved_estimated_cost_cny", sa.Numeric(20, 8)),
            ("charged_estimated_cost_cny", sa.Numeric(20, 8)),
        ):
            if name not in reservation_columns:
                batch_op.add_column(sa.Column(name, column_type))

    now = datetime.now(timezone.utc)
    free_plan_id = bind.execute(
        sa.text("SELECT id FROM quota_plans WHERE code = 'free'")
    ).scalar_one_or_none()
    if free_plan_id is None:
        return

    bind.execute(
        sa.text(
            "UPDATE quota_plans SET token_limit = :new_limit "
            "WHERE id = :plan_id AND token_limit = :old_limit"
        ),
        {
            "new_limit": NEW_TOKEN_LIMIT,
            "old_limit": OLD_TOKEN_LIMIT,
            "plan_id": free_plan_id,
        },
    )
    bind.execute(
        sa.text(
            "UPDATE quota_periods SET "
            "token_limit = :new_limit, "
            "policy_migration_version = :migration_mark "
            "WHERE token_limit = :old_limit "
            "AND period_end > :now "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM user_quota_assignments AS assignment "
            "  WHERE assignment.user_id = quota_periods.user_id "
            "  AND (assignment.token_limit_override IS NOT NULL "
            "       OR assignment.plan_id <> :plan_id)"
            ")"
        ),
        {
            "new_limit": NEW_TOKEN_LIMIT,
            "old_limit": OLD_TOKEN_LIMIT,
            "migration_mark": MIGRATION_MARK,
            "now": now,
            "plan_id": free_plan_id,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "policy_migration_version" not in _column_names(bind):
        return

    free_plan_id = bind.execute(
        sa.text("SELECT id FROM quota_plans WHERE code = 'free'")
    ).scalar_one_or_none()
    if free_plan_id is not None:
        bind.execute(
            sa.text(
                "UPDATE quota_periods SET token_limit = :old_limit "
                "WHERE token_limit = :new_limit "
                "AND policy_migration_version = :migration_mark "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM user_quota_assignments AS assignment "
                "  WHERE assignment.user_id = quota_periods.user_id "
                "  AND assignment.token_limit_override IS NOT NULL"
                ")"
            ),
            {
                "old_limit": OLD_TOKEN_LIMIT,
                "new_limit": NEW_TOKEN_LIMIT,
                "migration_mark": MIGRATION_MARK,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE quota_plans SET token_limit = :old_limit "
                "WHERE id = :plan_id AND token_limit = :new_limit"
            ),
            {
                "old_limit": OLD_TOKEN_LIMIT,
                "new_limit": NEW_TOKEN_LIMIT,
                "plan_id": free_plan_id,
            },
        )

    if "quota_policy_events" in sa.inspect(bind).get_table_names():
        op.drop_table("quota_policy_events")
    reservation_columns = _table_column_names(bind, "quota_reservations")
    with op.batch_alter_table("quota_reservations") as batch_op:
        for name in (
            "charged_estimated_cost_cny",
            "reserved_estimated_cost_cny",
            "output_price_snapshot",
            "input_price_snapshot",
            "reserved_output_tokens",
            "reserved_input_tokens",
        ):
            if name in reservation_columns:
                batch_op.drop_column(name)
    period_columns = _table_column_names(bind, "quota_periods")
    with op.batch_alter_table("quota_periods") as batch_op:
        for name in (
            "reserved_estimated_cost_cny",
            "used_estimated_cost_cny",
            "estimated_cost_limit_cny",
        ):
            if name in period_columns:
                batch_op.drop_column(name)
    assignment_columns = _table_column_names(bind, "user_quota_assignments")
    if "estimated_cost_limit_cny_override" in assignment_columns:
        with op.batch_alter_table("user_quota_assignments") as batch_op:
            batch_op.drop_column("estimated_cost_limit_cny_override")
    with op.batch_alter_table("quota_periods") as batch_op:
        batch_op.drop_column("policy_migration_version")
