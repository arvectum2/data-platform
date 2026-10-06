"""add managed consumer api keys

Revision ID: 0009_consumer_api_keys
Revises: 0008_sync_state
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_consumer_api_keys"
down_revision: str | Sequence[str] | None = "0008_sync_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dp_consumer_api_keys",
        sa.Column("key_id", sa.String(length=36), primary_key=True),
        sa.Column("consumer_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_dp_consumer_api_key_hash"),
    )
    op.create_index(
        "ix_dp_consumer_api_keys_consumer_status",
        "dp_consumer_api_keys",
        ["consumer_id", "status"],
    )
    op.create_index(
        "ix_dp_consumer_api_keys_tenant_status",
        "dp_consumer_api_keys",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dp_consumer_api_keys_tenant_status",
        table_name="dp_consumer_api_keys",
    )
    op.drop_index(
        "ix_dp_consumer_api_keys_consumer_status",
        table_name="dp_consumer_api_keys",
    )
    op.drop_table("dp_consumer_api_keys")
