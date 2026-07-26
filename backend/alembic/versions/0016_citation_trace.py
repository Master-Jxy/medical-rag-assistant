"""add citation document and chunk identifiers

Revision ID: 0016_citation_trace
Revises: 0015_parse_quality
"""

from alembic import op
import sqlalchemy as sa

revision = "0016_citation_trace"
down_revision = "0015_parse_quality"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("message_sources", sa.Column("document_id", sa.String(36)))
    op.add_column("message_sources", sa.Column("chunk_id", sa.String(100)))


def downgrade():
    op.drop_column("message_sources", "chunk_id")
    op.drop_column("message_sources", "document_id")
