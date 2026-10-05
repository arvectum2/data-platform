"""add continuous indexing state

Revision ID: 0008_sync_state
Revises: 0007_graph_relation_state
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008_sync_state"
down_revision: str | Sequence[str] | None = "0007_graph_relation_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.add_column("dp_resources", sa.Column("etag", sa.Text(), nullable=True))
    op.add_column("dp_resources", sa.Column("last_modified", sa.Text(), nullable=True))
    op.add_column("dp_resources", sa.Column("refresh_policy", json_type, nullable=False, server_default="{}"))
    op.add_column("dp_resources", sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_dp_resources_next_refresh", "dp_resources", ["next_refresh_at", "status"])
    op.create_table(
        "dp_refresh_runs",
        sa.Column("refresh_run_id", sa.String(length=36), primary_key=True),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("current_hash", sa.String(length=64), nullable=True),
        sa.Column("detail", json_type, nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["dp_resources.resource_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_dp_refresh_runs_resource_started", "dp_refresh_runs", ["resource_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_dp_refresh_runs_resource_started", table_name="dp_refresh_runs")
    op.drop_table("dp_refresh_runs")
    op.drop_index("ix_dp_resources_next_refresh", table_name="dp_resources")
    op.drop_column("dp_resources", "next_refresh_at")
    op.drop_column("dp_resources", "refresh_policy")
    op.drop_column("dp_resources", "last_modified")
    op.drop_column("dp_resources", "etag")
