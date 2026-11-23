"""Durable opt-in document-ingest queue; no change to synchronous ingest.

Revision ID: 0014_async_ingest_jobs
Revises: 0013_invoice_provider_status
Create Date: 2026-11-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0014_async_ingest_jobs"
down_revision: str | Sequence[str] | None = "0013_invoice_provider_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dp_async_ingest_jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column(
            "collection_id",
            sa.String(128),
            sa.ForeignKey("dp_collections.collection_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("canonical_uri", sa.Text(), nullable=True),
        sa.Column("title", sa.String(1024), nullable=True),
        sa.Column("pre_chunked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("input_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "result_json",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("error_class", sa.String(96), nullable=True),
        sa.UniqueConstraint(
            "collection_id", "idempotency_digest", name="uq_dp_async_ingest_idempotency"
        ),
    )
    op.create_index(
        "ix_dp_async_ingest_claim",
        "dp_async_ingest_jobs",
        ["status", "run_after", "lease_expires_at", "created_at"],
    )
    op.create_index("ix_dp_async_ingest_created", "dp_async_ingest_jobs", ["created_at"])
    op.create_index(
        "ix_dp_async_ingest_collection_status", "dp_async_ingest_jobs", ["collection_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_dp_async_ingest_created", table_name="dp_async_ingest_jobs")
    op.drop_index("ix_dp_async_ingest_collection_status", table_name="dp_async_ingest_jobs")
    op.drop_index("ix_dp_async_ingest_claim", table_name="dp_async_ingest_jobs")
    op.drop_table("dp_async_ingest_jobs")
