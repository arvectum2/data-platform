"""add relevance feedback

Revision ID: 0003_add_relevance_feedback
Revises: 0002_add_full_text_indexes
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_add_relevance_feedback"
down_revision: str | Sequence[str] | None = "0002_add_full_text_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "dp_relevance_feedback",
        sa.Column("feedback_id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("context", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["dp_collections.collection_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["dp_resources.resource_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["dp_documents.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["dp_chunks.chunk_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("feedback_id"),
    )
    op.create_index("ix_dp_feedback_collection_created", "dp_relevance_feedback", ["collection_id", "created_at"])
    op.create_index("ix_dp_feedback_query_hash", "dp_relevance_feedback", ["query_hash"])
    op.create_index("ix_dp_feedback_chunk_label", "dp_relevance_feedback", ["chunk_id", "label"])


def downgrade() -> None:
    op.drop_index("ix_dp_feedback_chunk_label", table_name="dp_relevance_feedback")
    op.drop_index("ix_dp_feedback_query_hash", table_name="dp_relevance_feedback")
    op.drop_index("ix_dp_feedback_collection_created", table_name="dp_relevance_feedback")
    op.drop_table("dp_relevance_feedback")
