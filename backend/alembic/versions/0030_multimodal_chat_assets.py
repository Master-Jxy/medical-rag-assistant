"""add private multimodal chat assets and observations"""

from alembic import op
import sqlalchemy as sa


revision = "0030_multimodal_chat_assets"
down_revision = "0029_dedup_version_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(50), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('uploaded','attached','deleted','expired','failed')", name="ck_media_assets_status"),
        sa.CheckConstraint("byte_size > 0 AND width > 0 AND height > 0", name="ck_media_assets_dimensions"),
    )
    op.create_index("ix_media_assets_user_id", "media_assets", ["user_id"])
    op.create_index("ix_media_assets_user_status_expires", "media_assets", ["user_id", "status", "expires_at"])
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("media_asset_id", sa.String(36), sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("surface", sa.String(20), nullable=False),
        sa.Column("conversation_message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE")),
        sa.Column("agent_message_id", sa.String(36), sa.ForeignKey("agent_messages.id", ondelete="CASCADE")),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("surface IN ('rag','agent')", name="ck_message_attachments_surface"),
        sa.CheckConstraint("(surface = 'rag' AND conversation_message_id IS NOT NULL AND agent_message_id IS NULL) OR (surface = 'agent' AND agent_message_id IS NOT NULL AND conversation_message_id IS NULL)", name="ck_message_attachments_target"),
        sa.UniqueConstraint("media_asset_id", name="uq_message_attachments_asset"),
        sa.UniqueConstraint("conversation_message_id", "position", name="uq_message_attachments_rag_position"),
        sa.UniqueConstraint("agent_message_id", "position", name="uq_message_attachments_agent_position"),
    )
    op.create_index("ix_message_attachments_media_asset_id", "message_attachments", ["media_asset_id"])
    op.create_table(
        "vision_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("media_asset_id", sa.String(36), sa.ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="CASCADE")),
        sa.Column("assistant_message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("focus_instruction_hash", sa.String(64)),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("observation_json", sa.JSON()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.CheckConstraint("kind IN ('overview','focused','report_extract')", name="ck_vision_observations_kind"),
        sa.CheckConstraint("status IN ('pending','completed','failed','stopped')", name="ck_vision_observations_status"),
        sa.UniqueConstraint("media_asset_id", "run_id", "assistant_message_id", "kind", "focus_instruction_hash", name="uq_vision_observations_idempotency"),
    )
    op.create_index("ix_vision_observations_media_asset_id", "vision_observations", ["media_asset_id"])
    op.create_index("ix_vision_observations_user_id", "vision_observations", ["user_id"])
    op.create_index("ix_vision_observations_asset_sequence", "vision_observations", ["media_asset_id", "sequence_no"])


def downgrade() -> None:
    op.drop_table("vision_observations")
    op.drop_table("message_attachments")
    op.drop_table("media_assets")
