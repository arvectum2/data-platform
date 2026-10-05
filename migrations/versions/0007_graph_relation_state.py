"""add graph review and temporal relation state

Revision ID: 0007_graph_relation_state
Revises: 0006_versioned_names
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_graph_relation_state"
down_revision: str | Sequence[str] | None = "0006_versioned_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dp_entity_relations",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="canonical"),
    )
    op.add_column(
        "dp_entity_relations",
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dp_entity_relations",
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_dp_entity_relations_status",
        "dp_entity_relations",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_dp_entity_relations_status", table_name="dp_entity_relations")
    op.drop_column("dp_entity_relations", "valid_to")
    op.drop_column("dp_entity_relations", "valid_from")
    op.drop_column("dp_entity_relations", "status")
