"""add invoice provider status

Revision ID: 0013_invoice_provider_status
Revises: 0012_billing_pricing_invoices
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_invoice_provider_status"
down_revision: str | Sequence[str] | None = "0012_billing_pricing_invoices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dp_invoices",
        sa.Column("provider_status", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_dp_invoices_provider_status",
        "dp_invoices",
        ["payment_provider", "provider_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_dp_invoices_provider_status", table_name="dp_invoices")
    op.drop_column("dp_invoices", "provider_status")
