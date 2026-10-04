"""add explicit entity relations

Revision ID: 0005_add_entity_relations
Revises: 0004_add_entities
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005_add_entity_relations"
down_revision: str | Sequence[str] | None = "0004_add_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "dp_entity_relations",
        sa.Column("relation_id", sa.String(length=64), nullable=False),
        sa.Column("source_entity_id", sa.String(length=36), nullable=False),
        sa.Column("target_entity_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=128), nullable=False),
        sa.Column("source_collection_id", sa.String(length=128), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("document_id", sa.String(length=64), nullable=True),
        sa.Column("chunk_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_entity_id"], ["dp_entities.entity_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"], ["dp_entities.entity_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_collection_id"], ["dp_collections.collection_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["dp_resources.resource_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["dp_documents.document_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["dp_chunks.chunk_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("relation_id"),
    )
    op.create_index(
        "ix_dp_entity_relations_source_type",
        "dp_entity_relations",
        ["source_entity_id", "relation_type"],
    )
    op.create_index(
        "ix_dp_entity_relations_target_type",
        "dp_entity_relations",
        ["target_entity_id", "relation_type"],
    )
    op.create_index(
        "ix_dp_entity_relations_chunk",
        "dp_entity_relations",
        ["chunk_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dp_entity_relations_chunk", table_name="dp_entity_relations")
    op.drop_index("ix_dp_entity_relations_target_type", table_name="dp_entity_relations")
    op.drop_index("ix_dp_entity_relations_source_type", table_name="dp_entity_relations")
    op.drop_table("dp_entity_relations")
