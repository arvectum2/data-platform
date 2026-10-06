"""add pricing catalogs and invoices

Revision ID: 0012_billing_pricing_invoices
Revises: 0011_connector_credentials
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0012_billing_pricing_invoices"
down_revision: str | Sequence[str] | None = "0011_connector_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")

    op.create_table(
        "dp_billing_catalogs",
        sa.Column("catalog_id", sa.String(length=36), primary_key=True),
        sa.Column("plan_code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("base_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("rules", json_type, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "plan_code",
            "version",
            name="uq_dp_billing_catalog_plan_version",
        ),
    )
    op.create_index(
        "ix_dp_billing_catalog_plan_effective",
        "dp_billing_catalogs",
        ["plan_code", "effective_from"],
    )

    op.create_table(
        "dp_tenant_billing_assignments",
        sa.Column("assignment_id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column(
            "catalog_id",
            sa.String(length=36),
            sa.ForeignKey("dp_billing_catalogs.catalog_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("payment_provider", sa.String(length=64), nullable=False),
        sa.Column("external_customer_id", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_dp_tenant_billing_tenant_effective",
        "dp_tenant_billing_assignments",
        ["tenant_id", "effective_from", "effective_to"],
    )
    op.create_index(
        "ix_dp_tenant_billing_catalog_status",
        "dp_tenant_billing_assignments",
        ["catalog_id", "status"],
    )

    op.create_table(
        "dp_invoices",
        sa.Column("invoice_id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column(
            "catalog_id",
            sa.String(length=36),
            sa.ForeignKey("dp_billing_catalogs.catalog_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("pricing_snapshot", json_type, nullable=False),
        sa.Column("usage_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payment_provider", sa.String(length=64), nullable=True),
        sa.Column("provider_reference", sa.String(length=256), nullable=True),
        sa.Column("payment_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "period_start",
            "period_end",
            name="uq_dp_invoice_tenant_period",
        ),
    )
    op.create_index(
        "ix_dp_invoices_tenant_status_period",
        "dp_invoices",
        ["tenant_id", "status", "period_end"],
    )

    op.create_table(
        "dp_invoice_lines",
        sa.Column("line_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.String(length=36),
            sa.ForeignKey("dp_invoices.invoice_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("included_quantity", sa.BigInteger(), nullable=False),
        sa.Column("chargeable_quantity", sa.BigInteger(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "invoice_id",
            "operation",
            "unit",
            name="uq_dp_invoice_line_meter",
        ),
    )
    op.create_index(
        "ix_dp_invoice_lines_invoice",
        "dp_invoice_lines",
        ["invoice_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dp_invoice_lines_invoice", table_name="dp_invoice_lines")
    op.drop_table("dp_invoice_lines")
    op.drop_index(
        "ix_dp_invoices_tenant_status_period",
        table_name="dp_invoices",
    )
    op.drop_table("dp_invoices")
    op.drop_index(
        "ix_dp_tenant_billing_catalog_status",
        table_name="dp_tenant_billing_assignments",
    )
    op.drop_index(
        "ix_dp_tenant_billing_tenant_effective",
        table_name="dp_tenant_billing_assignments",
    )
    op.drop_table("dp_tenant_billing_assignments")
    op.drop_index(
        "ix_dp_billing_catalog_plan_effective",
        table_name="dp_billing_catalogs",
    )
    op.drop_table("dp_billing_catalogs")
