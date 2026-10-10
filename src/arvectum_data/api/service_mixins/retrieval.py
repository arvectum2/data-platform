from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import load_only

from ...answers import GroundedAnswer, ReasoningAnswerSynthesizer
from ...research import ResearchResult, ResearchWorkflow
from ...indexing import (
    EmbeddingServerUnavailableError,
)
from ...modes import mode_profile
from ...models import ModelRole

from ...search import (
    HybridSearchEngine,
    PostgresSearchBackend,
    QueryExpansion,
    ReasoningQueryExpander,
    ReasoningReranker,
    RerankStrategy,
    SearchHit,
    SearchQuery,
    SearchStageDiagnostic,
)
from ...storage.postgres import (
    ChunkRow,
    CollectionRow,
    DataRepository,
    DocumentRow,
    PipelineRunRow,
    ResourceRow,
)

from ..service_support import (
    CollectionNotFound,
    CollectionAccessDenied,
    EmbeddingContractMismatch,
    IndexJobNotFound,
)


class RetrievalServiceMixin:
    def _runtime_embedding_contract(self) -> tuple[str, str, int | None]:
        return (
            self.embedding_provider.provider_name,
            self.embedding_provider.model_name,
            self.embedding_provider.dimension,
        )

    @staticmethod
    def _collection_embedding_contract(
        collection: CollectionRow,
    ) -> tuple[str | None, str | None, int | None]:
        return (
            collection.embedding_provider,
            collection.embedding_model,
            collection.embedding_dimension,
        )

    def _embedding_contract_matches(self, collection: CollectionRow) -> bool:
        expected_provider, expected_model, expected_dimension = self._collection_embedding_contract(
            collection
        )
        actual_provider, actual_model, actual_dimension = self._runtime_embedding_contract()
        if expected_provider != actual_provider or expected_model != actual_model:
            return False
        if (
            expected_dimension is not None
            and actual_dimension is not None
            and expected_dimension != actual_dimension
        ):
            return False
        return True

    def _validate_embedding_contract(self, collection: CollectionRow) -> None:
        if not self._embedding_contract_matches(collection):
            raise EmbeddingContractMismatch(
                f"collection {collection.collection_id!r} embedding contract "
                f"{self._collection_embedding_contract(collection)!r} does not match runtime "
                f"{self._runtime_embedding_contract()!r}; run an explicit index rebuild to migrate"
            )

    def _resolve_target_embedding_dimension(
        self,
        repo: DataRepository,
        collection_id: str,
        *,
        vectors: Sequence[Sequence[float]] | None = None,
    ) -> int | None:
        if vectors:
            dimensions = {len(vector) for vector in vectors}
            if len(dimensions) != 1:
                raise EmbeddingContractMismatch(
                    f"embedding provider returned inconsistent dimensions: {sorted(dimensions)}"
                )
            dimension = dimensions.pop()
            if self.embedding_provider.dimension is None:
                self.embedding_provider.dimension = dimension
            elif self.embedding_provider.dimension != dimension:
                raise EmbeddingContractMismatch(
                    f"runtime embedding dimension {self.embedding_provider.dimension} "
                    f"does not match generated dimension {dimension}"
                )
            return dimension
        if self.embedding_provider.dimension is not None:
            return int(self.embedding_provider.dimension)
        dimensions = repo.embedding_dimensions(
            collection_id,
            provider=self.embedding_provider.provider_name,
            model=self.embedding_provider.model_name,
        )
        if len(dimensions) == 1:
            return next(iter(dimensions))
        if len(dimensions) > 1:
            raise EmbeddingContractMismatch(
                f"multiple embedding dimensions exist for target model: {sorted(dimensions)}"
            )
        return None

    def _embed_texts_with_retry(
        self,
        texts: list[str],
    ) -> tuple[list[list[float]], int]:
        if not texts:
            return [], 0
        max_attempts = self.settings.embedding_retry_max_attempts
        for attempt in range(1, max_attempts + 1):
            try:
                return self.embedding_provider.embed_texts(texts), attempt
            except EmbeddingServerUnavailableError:
                if attempt >= max_attempts:
                    raise
                delay = min(
                    self.settings.embedding_retry_max_delay_seconds,
                    self.settings.embedding_retry_base_delay_seconds * (2 ** (attempt - 1)),
                )
                if delay > 0:
                    time.sleep(delay)
        raise RuntimeError("embedding retry loop exited unexpectedly")

    def _persist_and_index(self, result) -> dict[str, Any]:
        if len(result.chunks) > self.settings.max_chunks_per_ingest:
            raise ValueError(
                f"ingest exceeds max_chunks_per_ingest={self.settings.max_chunks_per_ingest}"
            )
        with self._require_factory()() as session:
            collection = session.get(CollectionRow, result.resource.collection_id)
            if collection is None:
                raise CollectionNotFound(result.resource.collection_id)
            self._validate_embedding_contract(collection)

            repo = DataRepository(session)
            existing_embedding_ids = repo.existing_embedding_chunk_ids(
                [chunk.chunk_id for chunk in result.chunks],
                provider=self.embedding_provider.provider_name,
                model=self.embedding_provider.model_name,
            )
            repo.persist_ingest(result)
            pending_chunks = [
                chunk for chunk in result.chunks if chunk.chunk_id not in existing_embedding_ids
            ]
            vectors, embedding_attempts = self._embed_texts_with_retry(
                [chunk.text for chunk in pending_chunks]
            )
            if len(vectors) != len(pending_chunks):
                raise RuntimeError("embedding provider returned unexpected vector count")
            dimensions = {len(vector) for vector in vectors}
            if len(dimensions) > 1 or 0 in dimensions:
                raise EmbeddingContractMismatch(
                    f"embedding provider returned invalid or inconsistent dimensions: "
                    f"{sorted(dimensions)}"
                )
            repo.upsert_embeddings(
                ((chunk.chunk_id, vector) for chunk, vector in zip(pending_chunks, vectors)),
                provider=self.embedding_provider.provider_name,
                model=self.embedding_provider.model_name,
            )
            if vectors:
                dimension = len(vectors[0])
                if collection.embedding_dimension is None:
                    collection.embedding_dimension = dimension
                elif collection.embedding_dimension != dimension:
                    raise EmbeddingContractMismatch(
                        f"collection {collection.collection_id!r} expects "
                        f"dimension {collection.embedding_dimension}, got {dimension}"
                    )
            session.commit()

            return {
                "collection_id": result.resource.collection_id,
                "resource_id": result.resource.resource_id,
                "document_id": result.document.document_id,
                "chunks": len(result.chunks),
                "chunks_indexed": len(result.chunks),
                "embeddings": len(result.chunks),
                "embeddings_written": len(vectors),
                "embeddings_skipped_existing": len(existing_embedding_ids),
                "embedding_attempts": embedding_attempts,
                "canonical_uri": result.resource.canonical_uri,
                "extraction_status": result.document.extraction_status,
            }

    @staticmethod
    def _collapse_canonical_hits(
        hits: Sequence[SearchHit],
        *,
        limit: int,
    ) -> list[SearchHit]:
        seen: set[str] = set()
        results: list[SearchHit] = []
        for hit in hits:
            canonical_uri = hit.canonical_uri.strip()
            key = canonical_uri or hit.chunk_id
            if key in seen:
                continue
            seen.add(key)
            results.append(hit)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _dedupe_federated_hits(
        hits: Sequence[SearchHit],
        *,
        limit: int,
    ) -> list[SearchHit]:
        winners: dict[str, str] = {}
        results: list[SearchHit] = []
        for hit in hits:
            canonical_uri = hit.canonical_uri.strip()
            collection_id = str(hit.metadata.get("collection_id") or "")
            if canonical_uri and collection_id:
                winner = winners.get(canonical_uri)
                if winner is None:
                    winners[canonical_uri] = collection_id
                elif winner != collection_id:
                    continue
            results.append(hit)
            if len(results) >= limit:
                break
        return results

    def search(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> list[SearchHit]:
        hits, _ = self.search_with_diagnostics(request, consumer=consumer)
        return hits

    def search_with_diagnostics(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> tuple[list[SearchHit], tuple[QueryExpansion, ...]]:
        hits, expansions, _ = self.search_with_execution_diagnostics(
            request,
            consumer=consumer,
        )
        return hits, expansions

    def search_with_execution_diagnostics(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> tuple[
        list[SearchHit],
        tuple[QueryExpansion, ...],
        tuple[SearchStageDiagnostic, ...],
    ]:
        self._validate_tenant_search_quota(request, consumer)
        with self._require_factory()() as session:
            # Preserve request-order authorization and error precedence, but
            # load all collection policies/contracts with one SQL round-trip.
            collections = {
                row.collection_id: row
                for row in session.scalars(
                    select(CollectionRow).where(
                        CollectionRow.collection_id.in_(request.collections)
                    )
                )
            }
            for collection_id in request.collections:
                collection = collections.get(collection_id)
                if collection is None:
                    raise CollectionNotFound(collection_id)
                self._authorize_collection_consumer(collection, consumer, session=session)
                self._validate_embedding_contract(collection)

            backend = PostgresSearchBackend(DataRepository(session))
            reasoning_provider = self.model_router.provider(ModelRole.REASONING)
            reranker = None
            if request.rerank:
                if request.rerank_strategy is RerankStrategy.CROSS_ENCODER:
                    reranker = self._cross_encoder_reranker(
                        max_candidates=request.rerank_candidates,
                    )
                elif reasoning_provider is not None:
                    reranker = ReasoningReranker(
                        reasoning_provider,
                        max_candidates=request.rerank_candidates,
                    )
            query_expander = (
                ReasoningQueryExpander(reasoning_provider)
                if request.expand_query and reasoning_provider is not None
                else None
            )
            engine = HybridSearchEngine(
                lexical_backend=backend,
                vector_backend=backend,
                embedding_provider=self.embedding_provider,
                reranker=reranker,
                query_expander=query_expander,
            )
            if len(request.collections) == 1 and not request.collapse_by_canonical_uri:
                hits = engine.search(request)
                return hits, engine.last_expansions, engine.last_diagnostics

            overfetch_factor = (
                4 if request.collapse_by_canonical_uri else min(max(len(request.collections), 2), 8)
            )
            expanded_limit = min(100, request.limit * overfetch_factor)
            expanded_rerank_candidates = max(
                request.rerank_candidates,
                expanded_limit,
            )
            if request.execution_mode is not None and request.rerank:
                profile = mode_profile(request.execution_mode)
                expanded_limit = min(
                    expanded_limit,
                    profile.max_rerank_candidates,
                )
                expanded_rerank_candidates = min(
                    expanded_rerank_candidates,
                    profile.max_rerank_candidates,
                )

            expanded_request = SearchQuery(
                query=request.query,
                collections=request.collections,
                filters=request.filters,
                limit=expanded_limit,
                mode=request.mode,
                lexical_weight=request.lexical_weight,
                vector_weight=request.vector_weight,
                query_variants=request.query_variants,
                query_variant_weight=request.query_variant_weight,
                expand_query=request.expand_query,
                query_expansion_limit=request.query_expansion_limit,
                collapse_by_canonical_uri=request.collapse_by_canonical_uri,
                rerank=request.rerank,
                rerank_candidates=expanded_rerank_candidates,
                rerank_strategy=request.rerank_strategy,
                execution_mode=request.execution_mode,
            )
            hits = engine.search(expanded_request)
            if request.collapse_by_canonical_uri:
                collapsed = self._collapse_canonical_hits(
                    hits,
                    limit=request.limit,
                )
                return collapsed, engine.last_expansions, engine.last_diagnostics
            return (
                self._dedupe_federated_hits(hits, limit=request.limit),
                engine.last_expansions,
                engine.last_diagnostics,
            )

    def answer(
        self,
        request: SearchQuery,
        *,
        consumer: str | None = None,
    ) -> tuple[GroundedAnswer, list[SearchHit]]:
        hits = self.search(request, consumer=consumer)
        reasoning_provider = self.model_router.provider(ModelRole.REASONING)
        if reasoning_provider is None:
            return (
                GroundedAnswer(
                    answer=None,
                    claims=(),
                    contradictions=(),
                    uncertainty="Reasoning provider is not configured.",
                    abstained=True,
                ),
                hits,
            )
        try:
            answer = ReasoningAnswerSynthesizer(
                reasoning_provider,
                max_hits=request.limit,
            ).synthesize(request.query, hits)
        except Exception as exc:
            answer = GroundedAnswer(
                answer=None,
                claims=(),
                contradictions=(),
                uncertainty=f"Synthesis unavailable: {type(exc).__name__}.",
                abstained=True,
            )
        return answer, hits

    def research(
        self,
        *,
        query: str,
        collection_id: str,
        connector: str = "duckduckgo_html",
        source_limit: int = 8,
        evidence_limit: int = 8,
        consumer: str | None = None,
        credential_id: str | None = None,
        rerank: bool = False,
        expand_query: bool = False,
    ) -> ResearchResult:
        if consumer is not None:
            with self._require_factory()() as session:
                collection = session.get(CollectionRow, collection_id)
                if collection is None:
                    raise CollectionNotFound(collection_id)
                self._authorize_collection_consumer(
                    collection,
                    consumer,
                    session=session,
                )
        if credential_id is not None and consumer is None:
            raise CollectionAccessDenied("research connector credential requires consumer identity")
        return ResearchWorkflow(self).run(
            query=query,
            collection_id=collection_id,
            connector=connector,
            source_limit=source_limit,
            evidence_limit=evidence_limit,
            consumer=consumer,
            credential_id=credential_id,
            rerank=rerank,
            expand_query=expand_query,
        )

    def _index_revision(
        self,
        collection: CollectionRow,
        chunks: Sequence[ChunkRow],
    ) -> str:
        # Preserve the historical byte-for-byte revision contract without
        # constructing a giant intermediate string for large collections.
        header = "\n".join(
            (
                f"provider={self.embedding_provider.provider_name}",
                f"model={self.embedding_provider.model_name}",
                f"dimension={self.embedding_provider.dimension}",
                f"language={collection.default_language}",
            )
        )
        digest = hashlib.sha256(header.encode("utf-8"))
        for chunk in sorted(chunks, key=lambda item: item.chunk_id):
            digest.update(b"\n")
            digest.update(f"{chunk.chunk_id}:{chunk.content_hash}".encode("utf-8"))
        return digest.hexdigest()

    @staticmethod
    def _job_payload(row: PipelineRunRow) -> dict[str, Any]:
        return {
            "run_id": row.run_id,
            "collection_id": row.collection_id,
            "run_type": row.run_type,
            "revision": row.revision,
            "status": row.status,
            "metrics": dict(row.metrics_json or {}),
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }

    def rebuild_index(self, collection_id: str) -> dict[str, Any]:
        factory = self._require_factory()
        run_id = str(uuid.uuid4())

        with factory() as session:
            collection = session.get(CollectionRow, collection_id)
            if collection is None:
                raise CollectionNotFound(collection_id)
            chunks = list(
                session.scalars(
                    select(ChunkRow)
                    .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
                    .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
                    .where(ResourceRow.collection_id == collection_id)
                    .options(load_only(ChunkRow.chunk_id, ChunkRow.content_hash))
                    .order_by(ChunkRow.chunk_id.asc())
                )
            )
            revision = self._index_revision(collection, chunks)
            existing_run = session.scalar(
                select(PipelineRunRow)
                .where(
                    PipelineRunRow.collection_id == collection_id,
                    PipelineRunRow.run_type == "reindex",
                    PipelineRunRow.revision == revision,
                )
                .limit(1)
            )

            if existing_run is not None:
                if (
                    collection.active_index_revision == revision
                    and existing_run.status == "completed"
                ):
                    return self._job_payload(existing_run)
                if existing_run.status in {"failed", "dead_letter"}:
                    run = existing_run
                    run_id = run.run_id
                    run.status = "running"
                    run.metrics_json = {}
                    run.started_at = datetime.now(UTC)
                    run.completed_at = None
                elif existing_run.status == "running":
                    return self._job_payload(existing_run)
                elif existing_run.status == "completed":
                    repo = DataRepository(session)
                    target_dimension = self._resolve_target_embedding_dimension(
                        repo,
                        collection_id,
                    )
                    repo.activate_collection_embedding(
                        collection_id,
                        provider=self.embedding_provider.provider_name,
                        model=self.embedding_provider.model_name,
                        dimension=target_dimension,
                        require_complete=True,
                    )
                    collection.active_index_revision = revision
                    session.commit()
                    return self._job_payload(existing_run)
                else:
                    raise RuntimeError(f"unsupported reindex job status: {existing_run.status}")
            else:
                run = PipelineRunRow(
                    run_id=run_id,
                    collection_id=collection_id,
                    run_type="reindex",
                    revision=revision,
                    status="running",
                    metrics_json={},
                    started_at=datetime.now(UTC),
                )
                session.add(run)

            session.commit()

        try:
            with factory() as session:
                collection = session.get(CollectionRow, collection_id)
                if collection is None:
                    raise CollectionNotFound(collection_id)
                chunks = list(
                    session.scalars(
                        select(ChunkRow)
                        .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
                        .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
                        .where(ResourceRow.collection_id == collection_id)
                        .order_by(ChunkRow.chunk_id.asc())
                    )
                )
                current_revision = self._index_revision(collection, chunks)
                if current_revision != revision:
                    raise RuntimeError("collection changed before reindex execution")

                vectors, embedding_attempts = self._embed_texts_with_retry(
                    [chunk.text for chunk in chunks]
                )
                if len(vectors) != len(chunks):
                    raise RuntimeError("embedding provider returned unexpected vector count")

                repo = DataRepository(session)
                target_dimension = self._resolve_target_embedding_dimension(
                    repo,
                    collection_id,
                    vectors=vectors,
                )
                previous_contract = self._collection_embedding_contract(collection)
                repo.upsert_embeddings(
                    ((chunk.chunk_id, vector) for chunk, vector in zip(chunks, vectors)),
                    provider=self.embedding_provider.provider_name,
                    model=self.embedding_provider.model_name,
                )

                final_chunks = list(
                    session.scalars(
                        select(ChunkRow)
                        .join(DocumentRow, DocumentRow.document_id == ChunkRow.document_id)
                        .join(ResourceRow, ResourceRow.resource_id == DocumentRow.resource_id)
                        .where(ResourceRow.collection_id == collection_id)
                        .options(load_only(ChunkRow.chunk_id, ChunkRow.content_hash))
                        .order_by(ChunkRow.chunk_id.asc())
                    )
                )
                if self._index_revision(collection, final_chunks) != revision:
                    raise RuntimeError("collection changed during reindex execution")

                run = session.get(PipelineRunRow, run_id)
                if run is None:
                    raise RuntimeError("reindex run disappeared")
                repo.activate_collection_embedding(
                    collection_id,
                    provider=self.embedding_provider.provider_name,
                    model=self.embedding_provider.model_name,
                    dimension=target_dimension,
                    require_complete=True,
                )
                target_contract = self._collection_embedding_contract(collection)
                run.status = "completed"
                run.metrics_json = {
                    "chunks_seen": len(chunks),
                    "embeddings_written": len(vectors),
                    "embedding_attempts": embedding_attempts,
                    "skipped_unchanged": False,
                    "embedding_migration": previous_contract != target_contract,
                    "embedding_provider": target_contract[0],
                    "embedding_model": target_contract[1],
                    "embedding_dimension": target_contract[2],
                }
                run.completed_at = datetime.now(UTC)
                collection.active_index_revision = revision
                session.commit()
                return self._job_payload(run)
        except Exception as exc:
            dead_letter = isinstance(exc, EmbeddingServerUnavailableError)
            attempts = self.settings.embedding_retry_max_attempts if dead_letter else 1
            with factory() as session:
                run = session.get(PipelineRunRow, run_id)
                if run is not None:
                    run.status = "dead_letter" if dead_letter else "failed"
                    run.metrics_json = {
                        "error_type": type(exc).__name__,
                        "embedding_attempts": attempts,
                        "dead_letter": dead_letter,
                    }
                    run.completed_at = datetime.now(UTC)
                    session.commit()
            raise

    def get_index_job(self, run_id: str) -> dict[str, Any]:
        with self._require_factory()() as session:
            row = session.get(PipelineRunRow, run_id)
            if row is None:
                raise IndexJobNotFound(run_id)
            return self._job_payload(row)

    def list_index_jobs(
        self,
        *,
        collection_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._require_factory()() as session:
            statement = select(PipelineRunRow)
            if collection_id:
                statement = statement.where(PipelineRunRow.collection_id == collection_id)
            statement = statement.order_by(
                PipelineRunRow.started_at.desc(),
                PipelineRunRow.run_id.asc(),
            ).limit(max(1, min(limit, 100)))
            return [self._job_payload(row) for row in session.scalars(statement)]
