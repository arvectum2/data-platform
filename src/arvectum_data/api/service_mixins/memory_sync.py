from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from ...acquisition.security import validate_public_url
from ...documents import ingest_url
from ...memory import MemoryConflictPolicy, MemoryKind, MemoryWrite, build_memory_ingest
from ...sync import RefreshPolicy, RefreshResult

from ...storage.postgres import (
    ChunkRow,
    CollectionRow,
    DataRecordRow,
    DocumentRow,
    ProvenanceRow,
    ResourceRow,
    RefreshRunRow,
)

from ..service_support import (
    CollectionNotFound,
    CollectionAccessDenied,
    MemoryNotFound,
)


class MemorySyncServiceMixin:
    def write_memory(
        self,
        *,
        collection_id: str,
        text: str,
        kind: MemoryKind | str,
        producer: str,
        consumer: str | None,
        title: str = "Memory",
        source_chunk_ids: Sequence[str] = (),
        model_provider: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        subject_key: str | None = None,
        conflict_policy: MemoryConflictPolicy | str = MemoryConflictPolicy.APPEND,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        resolved_kind = MemoryKind(kind)
        resolved_conflict = MemoryConflictPolicy(conflict_policy)
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            self._authorize_collection_consumer(collection, consumer, session=session)
            policy = dict(collection.access_policy or {})
            writers = tuple(str(x) for x in policy.get("memory_writers", []) if str(x))
            user_writers = tuple(str(x) for x in policy.get("user_memory_writers", []) if str(x))
            if resolved_kind is MemoryKind.USER_MEMORY:
                if consumer not in user_writers:
                    raise CollectionAccessDenied(collection_id)
            elif consumer not in writers:
                raise CollectionAccessDenied(collection_id)
            if producer != consumer:
                raise CollectionAccessDenied(collection_id)

            source_ids = tuple(dict.fromkeys(str(x) for x in source_chunk_ids if str(x)))
            source_rows = []
            if source_ids:
                source_rows = session.scalars(
                    select(ChunkRow).where(ChunkRow.chunk_id.in_(source_ids))
                ).all()
                if len(source_rows) != len(source_ids):
                    raise ValueError("all source_chunk_ids must exist")
                for chunk in source_rows:
                    source_collection = session.scalar(
                        select(ResourceRow.collection_id)
                        .join(DocumentRow, DocumentRow.resource_id == ResourceRow.resource_id)
                        .where(DocumentRow.document_id == chunk.document_id)
                    )
                    source = session.get(CollectionRow, source_collection)
                    self._authorize_collection_consumer(source, consumer, session=session)

            if (
                resolved_kind in {MemoryKind.SOURCE_EVIDENCE, MemoryKind.AGENT_OBSERVATION}
                and not source_ids
            ):
                raise ValueError("evidence and agent observations require source_chunk_ids")
            if resolved_kind is MemoryKind.SOURCE_EVIDENCE and not any(
                text.strip() in source.text for source in source_rows
            ):
                raise ValueError("source_evidence text must be an exact excerpt of a source chunk")

            active_conflict = None
            if subject_key:
                active_conflict = session.scalar(
                    select(DataRecordRow)
                    .join(ResourceRow, ResourceRow.resource_id == DataRecordRow.resource_id)
                    .where(
                        ResourceRow.collection_id == collection_id,
                        DataRecordRow.record_type == "agent_memory",
                        DataRecordRow.data_json["subject_key"].as_string() == subject_key,
                        DataRecordRow.review_status == "active",
                    )
                    .order_by(DataRecordRow.created_at.desc())
                    .limit(1)
                )
            if active_conflict is not None and resolved_conflict is MemoryConflictPolicy.REJECT:
                raise ValueError("active memory already exists for subject_key")
            active_conflict_id = active_conflict.record_id if active_conflict is not None else None

        write = MemoryWrite(
            collection_id=collection_id,
            text=text,
            kind=resolved_kind,
            producer=producer,
            title=title,
            source_chunk_ids=source_ids,
            model_provider=model_provider,
            model_name=model_name,
            model_version=model_version,
            subject_key=subject_key,
            conflict_policy=resolved_conflict,
            metadata=metadata,
        )
        result = build_memory_ingest(write)
        indexed = self._persist_and_index(result)

        with self._require_factory()() as session:
            if (
                active_conflict_id is not None
                and resolved_conflict is MemoryConflictPolicy.SUPERSEDE
            ):
                previous = session.get(DataRecordRow, active_conflict_id)
                if previous is not None:
                    previous.review_status = "superseded"
            record = DataRecordRow(
                record_id=f"memory:{result.resource.resource_id}",
                resource_id=result.resource.resource_id,
                document_id=result.document.document_id,
                record_type="agent_memory",
                data_json={
                    "text": text,
                    "kind": resolved_kind.value,
                    "producer": producer,
                    "subject_key": subject_key,
                    "source_chunk_ids": list(source_ids),
                    "model": {
                        "provider": model_provider,
                        "name": model_name,
                        "version": model_version,
                    },
                },
                review_status="active",
                metadata_json=dict(metadata or {}),
            )
            session.add(record)
            for source in source_rows:
                session.add(
                    ProvenanceRow(
                        resource_id=result.resource.resource_id,
                        document_id=result.document.document_id,
                        record_id=record.record_id,
                        chunk_id=source.chunk_id,
                        source_ref=f"chunk:{source.chunk_id}",
                        excerpt=source.text[:1000],
                        metadata_json={"relation": "derived_from"},
                    )
                )
            session.commit()
        return {
            **indexed,
            "record_id": record.record_id,
            "kind": resolved_kind.value,
            "producer": producer,
            "subject_key": subject_key,
            "source_chunk_ids": list(source_ids),
        }

    def delete_memory(self, record_id: str, *, consumer: str | None) -> None:
        with self._require_factory()() as session:
            record = session.get(DataRecordRow, record_id)
            if record is None or record.record_type != "agent_memory":
                raise MemoryNotFound(record_id)
            resource = session.get(ResourceRow, record.resource_id)
            collection = session.get(CollectionRow, resource.collection_id)
            self._authorize_collection_consumer(collection, consumer, session=session)
            policy = dict(collection.access_policy or {})
            writers = {
                str(x)
                for x in (
                    list(policy.get("memory_writers", []))
                    + list(policy.get("user_memory_writers", []))
                )
                if str(x)
            }
            if consumer not in writers:
                raise CollectionAccessDenied(collection.collection_id)
            session.delete(resource)
            session.commit()

    def configure_resource_refresh(
        self,
        resource_id: str,
        *,
        interval_seconds: int = 86400,
        missing_after_failures: int = 3,
        enabled: bool = True,
    ) -> dict[str, Any]:
        policy = RefreshPolicy(interval_seconds, missing_after_failures, enabled)
        with self._require_factory()() as session:
            resource = session.get(ResourceRow, resource_id)
            if resource is None:
                raise LookupError(resource_id)
            if resource.source_type != "url":
                raise ValueError("continuous refresh currently supports URL resources only")
            resource.refresh_policy = policy.as_dict()
            resource.next_refresh_at = policy.next_at()
            session.commit()
            return {
                "resource_id": resource.resource_id,
                "refresh_policy": dict(resource.refresh_policy),
                "next_refresh_at": resource.next_refresh_at,
                "status": resource.status,
            }

    def refresh_resource(self, resource_id: str) -> RefreshResult:
        now = datetime.now(UTC)
        with self._require_factory()() as session:
            resource = session.get(ResourceRow, resource_id)
            if resource is None:
                raise LookupError(resource_id)
            if resource.source_type != "url":
                raise ValueError("continuous refresh currently supports URL resources only")
            policy = RefreshPolicy.from_mapping(resource.refresh_policy)
            previous_hash = resource.content_hash
            collection_id = resource.collection_id
            url = resource.canonical_uri
            title = None
            latest_document = session.scalar(
                select(DocumentRow)
                .where(DocumentRow.resource_id == resource_id)
                .order_by(DocumentRow.created_at.desc())
                .limit(1)
            )
            if latest_document is not None:
                title = latest_document.title
            run = RefreshRunRow(
                resource_id=resource_id,
                started_at=now,
                outcome="running",
                previous_hash=previous_hash,
                detail_json={},
            )
            session.add(run)
            session.commit()
            run_id = run.refresh_run_id

        try:
            if not self.settings.allow_private_fetches:
                validate_public_url(url)
            candidate = ingest_url(
                url,
                collection_id=collection_id,
                title=title,
                acquisition=self.acquisition,
            )
            current_hash = candidate.resource.content_hash
            if current_hash == previous_hash:
                with self._require_factory()() as session:
                    resource = session.get(ResourceRow, resource_id)
                    run = session.get(RefreshRunRow, run_id)
                    resource.last_seen_at = now
                    resource.status = "ready"
                    resource.etag = candidate.resource.metadata.get("etag")
                    resource.last_modified = candidate.resource.metadata.get("last_modified")
                    resource.next_refresh_at = policy.next_at(now)
                    run.outcome = "unchanged"
                    run.current_hash = current_hash
                    run.completed_at = datetime.now(UTC)
                    session.commit()
                    return RefreshResult(
                        run_id,
                        resource_id,
                        "unchanged",
                        False,
                        previous_hash,
                        current_hash,
                        resource.next_refresh_at,
                        {},
                    )
            indexed = self._persist_and_index(candidate)
            with self._require_factory()() as session:
                resource = session.get(ResourceRow, resource_id)
                run = session.get(RefreshRunRow, run_id)
                resource.next_refresh_at = policy.next_at(now)
                run.outcome = "changed"
                run.current_hash = current_hash
                run.completed_at = datetime.now(UTC)
                run.detail_json = {
                    "document_id": indexed["document_id"],
                    "embeddings_written": indexed["embeddings_written"],
                }
                session.commit()
                return RefreshResult(
                    run_id,
                    resource_id,
                    "changed",
                    True,
                    previous_hash,
                    current_hash,
                    resource.next_refresh_at,
                    dict(run.detail_json),
                )
        except Exception as exc:
            with self._require_factory()() as session:
                resource = session.get(ResourceRow, resource_id)
                run = session.get(RefreshRunRow, run_id)
                previous_failures = int(
                    (resource.metadata_json or {}).get("consecutive_refresh_failures", 0)
                )
                failures = previous_failures + 1
                metadata = dict(resource.metadata_json or {})
                metadata["consecutive_refresh_failures"] = failures
                resource.metadata_json = metadata
                resource.status = (
                    "stale" if failures >= policy.missing_after_failures else "refresh_error"
                )
                resource.next_refresh_at = policy.next_at(now)
                run.outcome = resource.status
                run.completed_at = datetime.now(UTC)
                run.detail_json = {"error_type": type(exc).__name__}
                session.commit()
            return RefreshResult(
                run_id,
                resource_id,
                resource.status,
                False,
                previous_hash,
                None,
                resource.next_refresh_at,
                {"error_type": type(exc).__name__},
            )

    def refresh_due_resources(self, *, limit: int = 50) -> list[RefreshResult]:
        now = datetime.now(UTC)
        with self._require_factory()() as session:
            resource_ids = list(
                session.scalars(
                    select(ResourceRow.resource_id)
                    .where(
                        ResourceRow.next_refresh_at.is_not(None),
                        ResourceRow.next_refresh_at <= now,
                    )
                    .order_by(ResourceRow.next_refresh_at.asc())
                    .limit(max(1, min(limit, 200)))
                )
            )
        return [self.refresh_resource(resource_id) for resource_id in resource_ids]

    def list_refresh_runs(self, resource_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            rows = session.scalars(
                select(RefreshRunRow)
                .where(RefreshRunRow.resource_id == resource_id)
                .order_by(RefreshRunRow.started_at.desc())
                .limit(max(1, min(limit, 200)))
            ).all()
            return [
                {
                    "refresh_run_id": row.refresh_run_id,
                    "resource_id": row.resource_id,
                    "started_at": row.started_at,
                    "completed_at": row.completed_at,
                    "outcome": row.outcome,
                    "previous_hash": row.previous_hash,
                    "current_hash": row.current_hash,
                    "detail": dict(row.detail_json or {}),
                }
                for row in rows
            ]
