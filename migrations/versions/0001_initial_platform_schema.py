"""initial Data Platform PostgreSQL schema

Revision ID: 0001_initial_platform_schema
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0001_initial_platform_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_type():
    bind = op.get_bind()
    return JSONB() if bind.dialect.name == "postgresql" else sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    json_type = _json_type()

    op.create_table(
        "dp_collections",
        sa.Column("collection_id", sa.String(128), primary_key=True),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("default_language", sa.String(32), nullable=False, server_default="simple"),
        sa.Column("access_policy", json_type, nullable=False),
        sa.Column("retention_policy", json_type, nullable=False),
        sa.Column("embedding_provider", sa.String(128), nullable=True),
        sa.Column("embedding_model", sa.String(256), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("active_index_revision", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "name", name="uq_dp_collection_owner_name"),
    )

    op.create_table(
        "dp_resources",
        sa.Column("resource_id", sa.String(64), primary_key=True),
        sa.Column(
            "collection_id",
            sa.String(128),
            sa.ForeignKey("dp_collections.collection_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("canonical_uri", sa.Text(), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "collection_id",
            "source_type",
            "canonical_uri",
            name="uq_dp_resource_collection_source_uri",
        ),
    )
    op.create_index(
        "ix_dp_resources_collection_hash",
        "dp_resources",
        ["collection_id", "content_hash"],
    )

    op.create_table(
        "dp_documents",
        sa.Column("document_id", sa.String(64), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(64),
            sa.ForeignKey("dp_resources.resource_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("media_type", sa.String(256), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("extraction_status", sa.String(32), nullable=False),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "resource_id",
            "content_hash",
            name="uq_dp_document_resource_hash",
        ),
    )
    op.create_index("ix_dp_documents_resource", "dp_documents", ["resource_id"])

    op.create_table(
        "dp_records",
        sa.Column("record_id", sa.String(128), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(64),
            sa.ForeignKey("dp_resources.resource_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("dp_documents.document_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("record_type", sa.String(128), nullable=False),
        sa.Column("data", json_type, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="unreviewed"),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_dp_records_resource_type",
        "dp_records",
        ["resource_id", "record_type"],
    )

    op.create_table(
        "dp_chunks",
        sa.Column("chunk_id", sa.String(64), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("dp_documents.document_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "document_id",
            "ordinal",
            name="uq_dp_chunk_document_ordinal",
        ),
    )
    op.create_index(
        "ix_dp_chunks_document_hash",
        "dp_chunks",
        ["document_id", "content_hash"],
    )

    op.create_table(
        "dp_chunk_embeddings",
        sa.Column("embedding_id", sa.String(36), primary_key=True),
        sa.Column(
            "chunk_id",
            sa.String(64),
            sa.ForeignKey("dp_chunks.chunk_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model", sa.String(256), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("vector", VECTOR(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            name="uq_dp_chunk_embedding_identity",
        ),
    )
    op.create_index(
        "ix_dp_embeddings_provider_model",
        "dp_chunk_embeddings",
        ["provider", "model"],
    )

    op.create_table(
        "dp_provenance",
        sa.Column("provenance_id", sa.String(36), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(64),
            sa.ForeignKey("dp_resources.resource_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(64),
            sa.ForeignKey("dp_documents.document_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "chunk_id",
            sa.String(64),
            sa.ForeignKey("dp_chunks.chunk_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "record_id",
            sa.String(128),
            sa.ForeignKey("dp_records.record_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_dp_provenance_resource_document",
        "dp_provenance",
        ["resource_id", "document_id"],
    )
    op.create_index("ix_dp_provenance_chunk", "dp_provenance", ["chunk_id"])

    op.create_table(
        "dp_pipeline_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column(
            "collection_id",
            sa.String(128),
            sa.ForeignKey("dp_collections.collection_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_type", sa.String(32), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metrics", json_type, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "collection_id",
            "run_type",
            "revision",
            name="uq_dp_pipeline_run_revision",
        ),
    )
    op.create_index(
        "ix_dp_pipeline_runs_collection_type",
        "dp_pipeline_runs",
        ["collection_id", "run_type"],
    )


def downgrade() -> None:
    op.drop_table("dp_pipeline_runs")
    op.drop_table("dp_provenance")
    op.drop_table("dp_chunk_embeddings")
    op.drop_table("dp_chunks")
    op.drop_table("dp_records")
    op.drop_table("dp_documents")
    op.drop_table("dp_resources")
    op.drop_table("dp_collections")
