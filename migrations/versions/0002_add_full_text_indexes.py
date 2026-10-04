"""add multilingual full text indexes

Revision ID: 0002_add_full_text_indexes
Revises: 0001_initial_platform_schema
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


revision: str = "0002_add_full_text_indexes"
down_revision: str | Sequence[str] | None = "0001_initial_platform_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.add_column(
        "dp_chunks",
        sa.Column(
            "search_vector_simple",
            TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, coalesce(text, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "dp_chunks",
        sa.Column(
            "search_vector_russian",
            TSVECTOR(),
            sa.Computed(
                "to_tsvector('russian'::regconfig, coalesce(text, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "dp_chunks",
        sa.Column(
            "search_vector_english",
            TSVECTOR(),
            sa.Computed(
                "to_tsvector('english'::regconfig, coalesce(text, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_dp_chunks_fts_simple",
        "dp_chunks",
        ["search_vector_simple"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_dp_chunks_fts_russian",
        "dp_chunks",
        ["search_vector_russian"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_dp_chunks_fts_english",
        "dp_chunks",
        ["search_vector_english"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index("ix_dp_chunks_fts_english", table_name="dp_chunks")
    op.drop_index("ix_dp_chunks_fts_russian", table_name="dp_chunks")
    op.drop_index("ix_dp_chunks_fts_simple", table_name="dp_chunks")
    op.drop_column("dp_chunks", "search_vector_english")
    op.drop_column("dp_chunks", "search_vector_russian")
    op.drop_column("dp_chunks", "search_vector_simple")
