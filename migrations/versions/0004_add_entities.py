"""add deterministic entity resolution tables

Revision ID: 0004_add_entities
Revises: 0003_add_relevance_feedback
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_add_entities"
down_revision: str | Sequence[str] | None = "0003_add_relevance_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "dp_entities",
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("entity_id"),
    )
    op.create_index(
        "ix_dp_entities_type_name",
        "dp_entities",
        ["entity_type", "canonical_name"],
    )

    op.create_table(
        "dp_entity_aliases",
        sa.Column("alias_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("alias_kind", sa.String(length=64), nullable=False),
        sa.Column("alias_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("source_collection_id", sa.String(length=128), nullable=True),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["dp_entities.entity_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_collection_id"],
            ["dp_collections.collection_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("alias_id"),
        sa.UniqueConstraint(
            "entity_id",
            "alias_kind",
            "normalized_value",
            name="uq_dp_entity_alias_identity",
        ),
    )
    op.create_index(
        "ix_dp_entity_alias_lookup",
        "dp_entity_aliases",
        ["entity_type", "alias_kind", "normalized_value"],
    )
    op.create_index(
        "ix_dp_entity_alias_entity",
        "dp_entity_aliases",
        ["entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dp_entity_alias_entity", table_name="dp_entity_aliases")
    op.drop_index("ix_dp_entity_alias_lookup", table_name="dp_entity_aliases")
    op.drop_table("dp_entity_aliases")
    op.drop_index("ix_dp_entities_type_name", table_name="dp_entities")
    op.drop_table("dp_entities")
