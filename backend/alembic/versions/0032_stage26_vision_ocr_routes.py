"""extend vision route kinds for deterministic chat OCR routing"""

from alembic import op


revision = "0032_stage26_vision_ocr_routes"
down_revision = "0031_stage26_vision_scope"
branch_labels = None
depends_on = None


LEGACY_ROUTE_CONSTRAINT = (
    "route_kind IN ('pending','legacy','general','document','report')"
)
OCR_ROUTE_CONSTRAINT = (
    "route_kind IN ('pending','legacy','general','document','report',"
    "'overview_only','ocr_mode','reupload_required')"
)


def upgrade() -> None:
    with op.batch_alter_table("vision_observations") as batch_op:
        batch_op.drop_constraint(
            "ck_vision_observations_route_kind", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_vision_observations_route_kind", OCR_ROUTE_CONSTRAINT
        )


def downgrade() -> None:
    op.execute(
        "UPDATE vision_observations SET route_kind = CASE route_kind "
        "WHEN 'ocr_mode' THEN 'report' "
        "WHEN 'overview_only' THEN 'general' "
        "WHEN 'reupload_required' THEN 'general' "
        "ELSE route_kind END"
    )
    with op.batch_alter_table("vision_observations") as batch_op:
        batch_op.drop_constraint(
            "ck_vision_observations_route_kind", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_vision_observations_route_kind", LEGACY_ROUTE_CONSTRAINT
        )
