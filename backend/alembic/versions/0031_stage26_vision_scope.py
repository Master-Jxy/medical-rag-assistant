"""add deterministic vision observation scope and quality metadata"""

from alembic import op
import sqlalchemy as sa


revision = "0031_stage26_vision_scope"
down_revision = "0030_multimodal_chat_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("vision_observations") as batch_op:
        batch_op.add_column(sa.Column("observation_scope_id", sa.String(36)))
        batch_op.add_column(sa.Column("route_kind", sa.String(20)))
        batch_op.add_column(sa.Column("quality_status", sa.String(20)))
        batch_op.add_column(sa.Column("quality_codes", sa.JSON()))
        batch_op.add_column(sa.Column("provider_call_count", sa.Integer()))

    op.execute(
        "UPDATE vision_observations SET observation_scope_id = "
        "COALESCE(run_id, assistant_message_id, id), "
        "focus_instruction_hash = COALESCE(focus_instruction_hash, 'overview'), "
        "route_kind = 'legacy', quality_status = 'legacy', "
        "quality_codes = '[]', provider_call_count = 1"
    )

    with op.batch_alter_table("vision_observations") as batch_op:
        batch_op.drop_constraint(
            "uq_vision_observations_idempotency", type_="unique"
        )
        batch_op.alter_column(
            "observation_scope_id", existing_type=sa.String(36), nullable=False
        )
        batch_op.alter_column(
            "focus_instruction_hash", existing_type=sa.String(64), nullable=False
        )
        batch_op.alter_column(
            "route_kind", existing_type=sa.String(20), nullable=False
        )
        batch_op.alter_column(
            "quality_status", existing_type=sa.String(20), nullable=False
        )
        batch_op.alter_column(
            "quality_codes", existing_type=sa.JSON(), nullable=False
        )
        batch_op.alter_column(
            "provider_call_count", existing_type=sa.Integer(), nullable=False
        )
        batch_op.create_check_constraint(
            "ck_vision_observations_route_kind",
            "route_kind IN ('pending','legacy','general','document','report')",
        )
        batch_op.create_check_constraint(
            "ck_vision_observations_quality_status",
            "quality_status IN ('pending','legacy','pass','review','retry','failed')",
        )
        batch_op.create_check_constraint(
            "ck_vision_observations_provider_calls",
            "provider_call_count >= 0 AND provider_call_count <= 1",
        )
        batch_op.create_unique_constraint(
            "uq_vision_observations_scope",
            [
                "media_asset_id",
                "observation_scope_id",
                "kind",
                "focus_instruction_hash",
            ],
        )


def downgrade() -> None:
    with op.batch_alter_table("vision_observations") as batch_op:
        batch_op.drop_constraint("uq_vision_observations_scope", type_="unique")
        batch_op.drop_constraint(
            "ck_vision_observations_provider_calls", type_="check"
        )
        batch_op.drop_constraint(
            "ck_vision_observations_quality_status", type_="check"
        )
        batch_op.drop_constraint(
            "ck_vision_observations_route_kind", type_="check"
        )
        batch_op.alter_column(
            "focus_instruction_hash", existing_type=sa.String(64), nullable=True
        )
        batch_op.create_unique_constraint(
            "uq_vision_observations_idempotency",
            [
                "media_asset_id",
                "run_id",
                "assistant_message_id",
                "kind",
                "focus_instruction_hash",
            ],
        )
        batch_op.drop_column("provider_call_count")
        batch_op.drop_column("quality_codes")
        batch_op.drop_column("quality_status")
        batch_op.drop_column("route_kind")
        batch_op.drop_column("observation_scope_id")
