"""add metadata suggestions governance"""

from alembic import op
import sqlalchemy as sa


revision = "0028_metadata_suggestions"
down_revision = "0027_web_snapshot_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.add_column(sa.Column("disease_topics", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("document_type", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("published_year", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_document_versions_published_year",
            "published_year IS NULL OR (published_year >= 1900 AND published_year <= 2100)",
        )

    op.create_table(
        "metadata_suggestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("suggestion_source", sa.String(length=30), nullable=False),
        sa.Column("suggested_fields", sa.JSON(), nullable=False),
        sa.Column("confirmed_fields", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.JSON(), nullable=False),
        sa.Column("parse_warnings", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('suggested','accepted','edited','rejected')",
            name="ck_metadata_suggestions_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_metadata_suggestions_revision"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["knowledge_submissions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", name="uq_metadata_suggestions_submission"),
    )
    op.create_index(
        "ix_metadata_suggestions_submission",
        "metadata_suggestions",
        ["submission_id"],
    )
    op.create_index(
        "ix_metadata_suggestions_status_created",
        "metadata_suggestions",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_metadata_suggestions_status_created", table_name="metadata_suggestions"
    )
    op.drop_index("ix_metadata_suggestions_submission", table_name="metadata_suggestions")
    op.drop_table("metadata_suggestions")

    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_constraint(
            "ck_document_versions_published_year", type_="check"
        )
        batch_op.drop_column("published_year")
        batch_op.drop_column("document_type")
        batch_op.drop_column("disease_topics")
