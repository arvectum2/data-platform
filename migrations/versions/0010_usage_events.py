"""add durable usage events

Revision ID: 0010_usage_events
Revises: 0009_consumer_api_keys
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0010_usage_events"
down_revision: str | Sequence[str] | None = "0009_consumer_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "dp_usage_events",
        sa.Column("usage_event_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("consumer_id", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "consumer_id",
            "request_id",
            "operation",
            "unit",
            name="uq_dp_usage_consumer_request_operation_unit",
        ),
    )
    op.create_index(
        "ix_dp_usage_tenant_created",
        "dp_usage_events",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_dp_usage_tenant_operation_created",
        "dp_usage_events",
        ["tenant_id", "operation", "created_at"],
    )
    op.create_index(
        "ix_dp_usage_consumer_created",
        "dp_usage_events",
        ["consumer_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dp_usage_consumer_created", table_name="dp_usage_events")
    op.drop_index(
        "ix_dp_usage_tenant_operation_created",
        table_name="dp_usage_events",
    )
    op.drop_index("ix_dp_usage_tenant_created", table_name="dp_usage_events")
    op.drop_table("dp_usage_events")
