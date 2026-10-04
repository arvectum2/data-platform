"""allow versioned collections to reuse owner and name

Revision ID: 0006_versioned_names
Revises: 0005_add_entity_relations
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_versioned_names"
down_revision: str | Sequence[str] | None = "0005_add_entity_relations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_dp_collection_owner_name",
        "dp_collections",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_dp_collection_owner_name",
        "dp_collections",
        ["owner", "name"],
    )
