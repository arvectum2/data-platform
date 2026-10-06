"""add encrypted connector credentials

Revision ID: 0011_connector_credentials
Revises: 0010_usage_events
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0011_connector_credentials"
down_revision: str | Sequence[str] | None = "0010_usage_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "dp_connector_credentials",
        sa.Column("credential_id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("consumer_id", sa.String(length=128), nullable=False),
        sa.Column("connector_name", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("key_version", sa.String(length=32), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_dp_connector_credentials_tenant_connector_status",
        "dp_connector_credentials",
        ["tenant_id", "connector_name", "status"],
    )
    op.create_index(
        "ix_dp_connector_credentials_consumer_status",
        "dp_connector_credentials",
        ["consumer_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dp_connector_credentials_consumer_status",
        table_name="dp_connector_credentials",
    )
    op.drop_index(
        "ix_dp_connector_credentials_tenant_connector_status",
        table_name="dp_connector_credentials",
    )
    op.drop_table("dp_connector_credentials")
