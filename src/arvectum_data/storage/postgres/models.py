from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class CollectionRow(TimestampMixin, Base):
    __tablename__ = "dp_collections"

    collection_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    default_language: Mapped[str] = mapped_column(String(32), default="simple", nullable=False)
    access_policy: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    retention_policy: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    embedding_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_index_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)

class ResourceRow(TimestampMixin, Base):
    __tablename__ = "dp_resources"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("dp_collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_uri: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_policy: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )

    collection: Mapped[CollectionRow] = relationship()
    documents: Mapped[list[DocumentRow]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "source_type",
            "canonical_uri",
            name="uq_dp_resource_collection_source_uri",
        ),
        Index("ix_dp_resources_collection_hash", "collection_id", "content_hash"),
        Index("ix_dp_resources_next_refresh", "next_refresh_at", "status"),
    )


class RefreshRunRow(Base):
    __tablename__ = "dp_refresh_runs"

    refresh_run_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("dp_resources.resource_id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail_json: Mapped[dict[str, Any]] = mapped_column("detail", JSON_TYPE, default=dict, nullable=False)

    __table_args__ = (
        Index("ix_dp_refresh_runs_resource_started", "resource_id", "started_at"),
    )


class DocumentRow(TimestampMixin, Base):
    __tablename__ = "dp_documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("dp_resources.resource_id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    media_type: Mapped[str] = mapped_column(String(256), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_status: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )

    resource: Mapped[ResourceRow] = relationship(back_populates="documents")
    chunks: Mapped[list[ChunkRow]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("resource_id", "content_hash", name="uq_dp_document_resource_hash"),
        Index("ix_dp_documents_resource", "resource_id"),
    )


class DataRecordRow(TimestampMixin, Base):
    __tablename__ = "dp_records"

    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("dp_resources.resource_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_documents.document_id", ondelete="CASCADE"),
        nullable=True,
    )
    record_type: Mapped[str] = mapped_column(String(128), nullable=False)
    data_json: Mapped[dict[str, Any]] = mapped_column("data", JSON_TYPE, default=dict, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), default="unreviewed", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )

    __table_args__ = (
        Index("ix_dp_records_resource_type", "resource_id", "record_type"),
    )


class ChunkRow(TimestampMixin, Base):
    __tablename__ = "dp_chunks"

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("dp_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector_simple: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, coalesce(text, ''))",
            persisted=True,
        ),
        nullable=True,
    )
    search_vector_russian: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('russian'::regconfig, coalesce(text, ''))",
            persisted=True,
        ),
        nullable=True,
    )
    search_vector_english: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english'::regconfig, coalesce(text, ''))",
            persisted=True,
        ),
        nullable=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )

    document: Mapped[DocumentRow] = relationship(back_populates="chunks")
    embeddings: Mapped[list[ChunkEmbeddingRow]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_dp_chunk_document_ordinal"),
        Index("ix_dp_chunks_document_hash", "document_id", "content_hash"),
    )


class ChunkEmbeddingRow(Base):
    __tablename__ = "dp_chunk_embeddings"

    embedding_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("dp_chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(256), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(VECTOR(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    chunk: Mapped[ChunkRow] = relationship(back_populates="embeddings")

    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "provider",
            "model",
            name="uq_dp_chunk_embedding_identity",
        ),
        Index("ix_dp_embeddings_provider_model", "provider", "model"),
    )


class ProvenanceRow(Base):
    __tablename__ = "dp_provenance"

    provenance_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("dp_resources.resource_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_documents.document_id", ondelete="CASCADE"),
        nullable=True,
    )
    chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_chunks.chunk_id", ondelete="CASCADE"),
        nullable=True,
    )
    record_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_records.record_id", ondelete="CASCADE"),
        nullable=True,
    )
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_dp_provenance_resource_document", "resource_id", "document_id"),
        Index("ix_dp_provenance_chunk", "chunk_id"),
    )






class EntityRow(TimestampMixin, Base):
    __tablename__ = "dp_entities"

    entity_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )

    aliases: Mapped[list["EntityAliasRow"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_dp_entities_type_name", "entity_type", "canonical_name"),
    )


class EntityAliasRow(Base):
    __tablename__ = "dp_entity_aliases"

    alias_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("dp_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    alias_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    alias_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)
    source_collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_collections.collection_id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    entity: Mapped[EntityRow] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "alias_kind",
            "normalized_value",
            name="uq_dp_entity_alias_identity",
        ),
        Index(
            "ix_dp_entity_alias_lookup",
            "entity_type",
            "alias_kind",
            "normalized_value",
        ),
        Index("ix_dp_entity_alias_entity", "entity_id"),
    )



class EntityRelationRow(Base):
    __tablename__ = "dp_entity_relations"

    relation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_entity_id: Mapped[str] = mapped_column(
        ForeignKey("dp_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_entity_id: Mapped[str] = mapped_column(
        ForeignKey("dp_entities.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="canonical", nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_collections.collection_id", ondelete="SET NULL"),
        nullable=True,
    )
    resource_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_resources.resource_id", ondelete="SET NULL"),
        nullable=True,
    )
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_documents.document_id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("dp_chunks.chunk_id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "ix_dp_entity_relations_source_type",
            "source_entity_id",
            "relation_type",
        ),
        Index(
            "ix_dp_entity_relations_target_type",
            "target_entity_id",
            "relation_type",
        ),
        Index("ix_dp_entity_relations_chunk", "chunk_id"),
        Index("ix_dp_entity_relations_status", "status"),
    )

class RelevanceFeedbackRow(Base):
    __tablename__ = "dp_relevance_feedback"

    feedback_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("dp_collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("dp_resources.resource_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("dp_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("dp_chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
    )
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context_json: Mapped[dict[str, Any]] = mapped_column(
        "context", JSON_TYPE, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_dp_feedback_collection_created", "collection_id", "created_at"),
        Index("ix_dp_feedback_query_hash", "query_hash"),
        Index("ix_dp_feedback_chunk_label", "chunk_id", "label"),
    )


class ConsumerApiKeyRow(Base):
    __tablename__ = "dp_consumer_api_keys"

    key_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    consumer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_dp_consumer_api_keys_consumer_status", "consumer_id", "status"),
        Index("ix_dp_consumer_api_keys_tenant_status", "tenant_id", "status"),
    )


class ConnectorCredentialRow(Base):
    __tablename__ = "dp_connector_credentials"

    credential_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    consumer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_dp_connector_credentials_tenant_connector_status",
            "tenant_id",
            "connector_name",
            "status",
        ),
        Index(
            "ix_dp_connector_credentials_consumer_status",
            "consumer_id",
            "status",
        ),
    )


class BillingCatalogRow(Base):
    __tablename__ = "dp_billing_catalogs"

    catalog_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    plan_code: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    base_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rules_json: Mapped[list[dict[str, Any]]] = mapped_column(
        "rules", JSON_TYPE, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "plan_code",
            "version",
            name="uq_dp_billing_catalog_plan_version",
        ),
        Index(
            "ix_dp_billing_catalog_plan_effective",
            "plan_code",
            "effective_from",
        ),
    )


class TenantBillingRow(Base):
    __tablename__ = "dp_tenant_billing"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(
        ForeignKey("dp_billing_catalogs.catalog_id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_provider: Mapped[str] = mapped_column(
        String(64), default="manual", nullable=False
    )
    external_customer_id: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    __table_args__ = (
        Index(
            "ix_dp_tenant_billing_catalog_status",
            "catalog_id",
            "status",
        ),
    )


class InvoiceRow(Base):
    __tablename__ = "dp_invoices"

    invoice_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    catalog_id: Mapped[str] = mapped_column(
        ForeignKey("dp_billing_catalogs.catalog_id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    pricing_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, default=dict, nullable=False
    )
    usage_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payment_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "period_start",
            "period_end",
            name="uq_dp_invoice_tenant_period",
        ),
        Index(
            "ix_dp_invoices_tenant_status_period",
            "tenant_id",
            "status",
            "period_end",
        ),
    )


class InvoiceLineRow(Base):
    __tablename__ = "dp_invoice_lines"

    line_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("dp_invoices.invoice_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    included_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chargeable_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "operation",
            "unit",
            name="uq_dp_invoice_line_meter",
        ),
        Index("ix_dp_invoice_lines_invoice", "invoice_id"),
    )


class UsageEventRow(Base):
    __tablename__ = "dp_usage_events"

    usage_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    consumer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "consumer_id",
            "request_id",
            "operation",
            "unit",
            name="uq_dp_usage_consumer_request_operation_unit",
        ),
        Index("ix_dp_usage_tenant_created", "tenant_id", "created_at"),
        Index(
            "ix_dp_usage_tenant_operation_created",
            "tenant_id",
            "operation",
            "created_at",
        ),
        Index("ix_dp_usage_consumer_created", "consumer_id", "created_at"),
    )


class PipelineRunRow(Base):
    __tablename__ = "dp_pipeline_runs"

    run_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("dp_collections.collection_id", ondelete="CASCADE"),
        nullable=False,
    )
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(
        "metrics", JSON_TYPE, default=dict, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_dp_pipeline_runs_collection_type", "collection_id", "run_type"),
        UniqueConstraint(
            "collection_id",
            "run_type",
            "revision",
            name="uq_dp_pipeline_run_revision",
        ),
    )
