"""user quota plans periods and reservations"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = "0024_user_quota"
down_revision = "0023_usage_groups"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("quota_plans",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False), sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("token_limit", sa.Integer(), nullable=False), sa.Column("request_limit", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_limit_cny", sa.Numeric(20,8)), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    now = datetime.now(timezone.utc)
    op.bulk_insert(sa.table("quota_plans", sa.column("id"), sa.column("code"), sa.column("name"), sa.column("period_type"),
        sa.column("token_limit"), sa.column("request_limit"), sa.column("estimated_cost_limit_cny"), sa.column("enabled"),
        sa.column("created_at"), sa.column("updated_at")), [{
            "id":"00000000-0000-0000-0000-000000000001","code":"free","name":"免费计划","period_type":"monthly",
            "token_limit":100000,"request_limit":500,"estimated_cost_limit_cny":None,"enabled":True,"created_at":now,"updated_at":now}])
    op.create_table("user_quota_assignments",
        sa.Column("user_id", sa.String(36), primary_key=True), sa.Column("plan_id", sa.String(36), nullable=False),
        sa.Column("token_limit_override", sa.Integer()), sa.Column("request_limit_override", sa.Integer()),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False), sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.String(36)), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["plan_id"], ["quota_plans.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"))
    op.create_table("quota_periods",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False), sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_limit", sa.Integer(), nullable=False), sa.Column("request_limit", sa.Integer(), nullable=False),
        sa.Column("used_tokens", sa.Integer(), nullable=False), sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("used_requests", sa.Integer(), nullable=False), sa.Column("reserved_requests", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_quota_periods_user_id", "quota_periods", ["user_id"])
    op.create_index("uq_quota_period_user_range", "quota_periods", ["user_id","period_start","period_end"], unique=True)
    op.create_table("quota_reservations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), nullable=False), sa.Column("quota_period_id", sa.String(36), nullable=False),
        sa.Column("surface", sa.String(20), nullable=False), sa.Column("usage_group_id", sa.String(36), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False), sa.Column("charged_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quota_period_id"], ["quota_periods.id"], ondelete="CASCADE"))
    op.create_index("ix_quota_reservations_user_id", "quota_reservations", ["user_id"])

def downgrade():
    op.drop_table("quota_reservations")
    op.drop_table("quota_periods")
    op.drop_table("user_quota_assignments")
    op.drop_table("quota_plans")
