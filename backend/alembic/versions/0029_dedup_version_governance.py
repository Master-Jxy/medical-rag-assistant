"""add duplicate version governance fields"""

from alembic import op
import sqlalchemy as sa


revision = "0029_dedup_version_governance"
down_revision = "0028_metadata_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_submissions") as batch_op:
        batch_op.add_column(sa.Column("normalized_text_hash", sa.String(length=64)))
        batch_op.add_column(
            sa.Column("normalized_text_hash_version", sa.String(length=40))
        )
        batch_op.add_column(
            sa.Column("near_duplicate_fingerprint", sa.String(length=16))
        )
        batch_op.add_column(
            sa.Column("near_duplicate_fingerprint_version", sa.String(length=40))
        )
        batch_op.add_column(sa.Column("duplicate_decision", sa.String(length=20)))
        batch_op.add_column(sa.Column("duplicate_target_document_id", sa.String(length=36)))
        batch_op.add_column(sa.Column("duplicate_decision_reason", sa.String(length=500)))
        batch_op.create_foreign_key(
            "fk_knowledge_submissions_duplicate_target_document",
            "documents",
            ["duplicate_target_document_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_knowledge_submissions_duplicate_decision",
            "duplicate_decision IS NULL OR duplicate_decision IN "
            "('new','version','rejected')",
        )
        batch_op.create_index(
            "ix_knowledge_submissions_normalized_hash",
            ["normalized_text_hash", "normalized_text_hash_version"],
        )

    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_constraint("ck_document_versions_review_status", type_="check")
        batch_op.add_column(sa.Column("supersedes_document_id", sa.String(length=36)))
        batch_op.add_column(sa.Column("change_reason", sa.String(length=500)))
        batch_op.add_column(sa.Column("parser_version", sa.String(length=80)))
        batch_op.add_column(sa.Column("corpus_version", sa.String(length=80)))
        batch_op.add_column(sa.Column("normalized_text_hash", sa.String(length=64)))
        batch_op.add_column(
            sa.Column("normalized_text_hash_version", sa.String(length=40))
        )
        batch_op.add_column(
            sa.Column("near_duplicate_fingerprint", sa.String(length=16))
        )
        batch_op.add_column(
            sa.Column("near_duplicate_fingerprint_version", sa.String(length=40))
        )
        batch_op.create_foreign_key(
            "fk_document_versions_supersedes_document",
            "documents",
            ["supersedes_document_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_document_versions_review_status",
            "review_status IN ('current','due','in_review','expired')",
        )
        batch_op.create_unique_constraint(
            "uq_document_versions_supersedes_version",
            ["supersedes_document_id", "version"],
        )
        batch_op.create_index(
            "ix_document_versions_supersedes",
            ["supersedes_document_id"],
        )
        batch_op.create_index(
            "ix_document_versions_normalized_hash",
            ["normalized_text_hash", "normalized_text_hash_version"],
        )


def downgrade() -> None:
    op.execute(
        "UPDATE document_versions SET review_status = 'due' "
        "WHERE review_status = 'expired'"
    )
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_index("ix_document_versions_normalized_hash")
        batch_op.drop_index("ix_document_versions_supersedes")
        batch_op.drop_constraint("uq_document_versions_supersedes_version", type_="unique")
        batch_op.drop_constraint("ck_document_versions_review_status", type_="check")
        batch_op.drop_constraint(
            "fk_document_versions_supersedes_document", type_="foreignkey"
        )
        batch_op.drop_column("near_duplicate_fingerprint_version")
        batch_op.drop_column("near_duplicate_fingerprint")
        batch_op.drop_column("normalized_text_hash_version")
        batch_op.drop_column("normalized_text_hash")
        batch_op.drop_column("corpus_version")
        batch_op.drop_column("parser_version")
        batch_op.drop_column("change_reason")
        batch_op.drop_column("supersedes_document_id")
        batch_op.create_check_constraint(
            "ck_document_versions_review_status",
            "review_status IN ('current','due','in_review')",
        )

    with op.batch_alter_table("knowledge_submissions") as batch_op:
        batch_op.drop_index("ix_knowledge_submissions_normalized_hash")
        batch_op.drop_constraint(
            "ck_knowledge_submissions_duplicate_decision", type_="check"
        )
        batch_op.drop_constraint(
            "fk_knowledge_submissions_duplicate_target_document", type_="foreignkey"
        )
        batch_op.drop_column("duplicate_decision_reason")
        batch_op.drop_column("duplicate_target_document_id")
        batch_op.drop_column("duplicate_decision")
        batch_op.drop_column("near_duplicate_fingerprint_version")
        batch_op.drop_column("near_duplicate_fingerprint")
        batch_op.drop_column("normalized_text_hash_version")
        batch_op.drop_column("normalized_text_hash")
