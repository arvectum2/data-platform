from __future__ import annotations

from typing import Any, Self, cast

import httpx

from .models import (
    Collection,
    CollectionStats,
    ConsumerContract,
    ConnectorCredential,
    DiscoveryResponse,
    Entity,
    EntityAliasInput,
    EntityRelation,
    EntityResolveResponse,
    IngestResult,
    ProcessedDocument,
    SearchHit,
    SearchProfile,
    SearchResponse,
)


class DataPlatformError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.path = path


class DataPlatformClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout_seconds: int | float = 30,
        consumer: str = "",
        consumer_key: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized:
            raise ValueError("Data Platform base URL must not be blank")
        headers = {"X-Arvectum-Key": api_key} if api_key else {}
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=normalized,
            timeout=timeout_seconds,
            headers=headers,
        )
        self._consumer = consumer.strip()
        self._consumer_key = consumer_key

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _error(
        self,
        response: httpx.Response,
        method: str,
        path: str,
    ) -> DataPlatformError:
        detail = response.text.strip()[:500]
        return DataPlatformError(
            f"Data Platform {method} {path} returned HTTP {response.status_code}: {detail}",
            status_code=response.status_code,
            method=method,
            path=path,
        )

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DataPlatformError(
                f"Data Platform request failed: {exc}",
                method=method,
                path=path,
            ) from exc
        if response.status_code >= 400:
            raise self._error(response, method, path)
        return response

    def request_json(self, method: str, path: str, **kwargs) -> Any:
        return self._request(method, path, **kwargs).json()

    def _consumer_headers_required(self) -> dict[str, str]:
        if not self._consumer or not self._consumer_key:
            raise DataPlatformError(
                "consumer credentials are required for this Data Platform operation"
            )
        return {
            "X-Arvectum-Consumer": self._consumer,
            "X-Arvectum-Consumer-Key": self._consumer_key,
        }

    def health(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.request_json("GET", "/health"))

    def contract(self) -> ConsumerContract:
        return cast(ConsumerContract, self.request_json("GET", "/v1/contract"))

    def require_contract(self, major: int = 1) -> ConsumerContract:
        contract = self.contract()
        try:
            actual_major = int(str(contract["version"]).split(".", 1)[0])
        except (KeyError, TypeError, ValueError) as exc:
            raise DataPlatformError(
                "Data Platform returned invalid consumer contract"
            ) from exc
        if actual_major != major:
            raise DataPlatformError(
                "Incompatible Data Platform consumer contract: "
                f"required major {major}, server reports {contract['version']}"
            )
        return contract

    def ensure_collection(
        self,
        *,
        collection_id: str,
        name: str,
        owner: str,
        default_language: str = "russian",
        access_policy: dict[str, Any] | None = None,
    ) -> Collection:
        path = f"/v1/collections/{collection_id}"
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise DataPlatformError(
                f"Data Platform collection lookup failed: {exc}",
                method="GET",
                path=path,
            ) from exc
        if response.status_code == 200:
            return cast(Collection, response.json())
        if response.status_code != 404:
            raise self._error(response, "GET", path)
        payload: dict[str, Any] = {
            "collection_id": collection_id,
            "owner": owner,
            "name": name,
            "default_language": default_language,
        }
        if access_policy is not None:
            payload["access_policy"] = access_policy
        return cast(
            Collection,
            self.request_json("POST", "/v1/collections", json=payload),
        )

    def collection_exists(self, collection_id: str) -> bool:
        path = f"/v1/collections/{collection_id}"
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise DataPlatformError(
                f"Data Platform request failed: {exc}",
                method="GET",
                path=path,
            ) from exc
        if response.status_code == 200:
            return True
        if response.status_code == 404:
            return False
        raise self._error(response, "GET", path)

    def collection_stats(self, collection_id: str) -> CollectionStats:
        return cast(
            CollectionStats,
            self.request_json(
                "GET",
                f"/v1/collections/{collection_id}/stats",
            ),
        )

    def process_document(
        self,
        *,
        collection_id: str,
        canonical_uri: str,
        title: str,
        content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        chunk_size_chars: int = 1500,
        overlap_chars: int = 200,
        min_chunk_chars: int = 120,
        max_chars: int = 2_000_000,
    ) -> ProcessedDocument:
        return cast(
            ProcessedDocument,
            self.request_json(
                "POST",
                "/v1/process/document",
                data={
                    "collection_id": collection_id,
                    "title": title,
                    "canonical_uri": canonical_uri,
                    "chunk_size_chars": str(chunk_size_chars),
                    "overlap_chars": str(overlap_chars),
                    "min_chunk_chars": str(min_chunk_chars),
                    "max_chars": str(max_chars),
                },
                files={"file": (filename, content, content_type)},
            ),
        )

    def ingest_document_bytes(
        self,
        *,
        collection_id: str,
        canonical_uri: str,
        title: str,
        content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        pre_chunked: bool = False,
    ) -> IngestResult:
        return cast(
            IngestResult,
            self.request_json(
                "POST",
                "/v1/ingest/document",
                data={
                    "collection_id": collection_id,
                    "title": title,
                    "canonical_uri": canonical_uri,
                    "pre_chunked": "true" if pre_chunked else "false",
                },
                files={"file": (filename, content, content_type)},
            ),
        )

    def ingest_document(
        self,
        *,
        collection_id: str,
        canonical_uri: str,
        title: str,
        text: str,
        filename: str,
        pre_chunked: bool = True,
    ) -> IngestResult:
        return self.ingest_document_bytes(
            collection_id=collection_id,
            canonical_uri=canonical_uri,
            title=title,
            content=text.encode("utf-8"),
            filename=filename,
            content_type="text/plain",
            pre_chunked=pre_chunked,
        )

    def ingest_url(
        self,
        *,
        collection_id: str,
        url: str,
        title: str | None = None,
    ) -> IngestResult:
        payload: dict[str, Any] = {
            "collection_id": collection_id,
            "url": url,
        }
        if title is not None:
            payload["title"] = title
        return cast(
            IngestResult,
            self.request_json("POST", "/v1/ingest/url", json=payload),
        )

    def write_memory(
        self,
        *,
        collection_id: str,
        text: str,
        kind: str,
        title: str = "Memory",
        source_chunk_ids: list[str] | None = None,
        model_provider: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        subject_key: str | None = None,
        conflict_policy: str = "append",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "X-Arvectum-Consumer": self._consumer,
            "X-Arvectum-Consumer-Key": self._consumer_key,
        }
        return cast(
            dict[str, Any],
            self.request_json(
                "POST",
                "/v1/memory",
                headers=headers,
                json={
                    "collection_id": collection_id,
                    "text": text,
                    "kind": kind,
                    "title": title,
                    "source_chunk_ids": source_chunk_ids or [],
                    "model_provider": model_provider,
                    "model_name": model_name,
                    "model_version": model_version,
                    "subject_key": subject_key,
                    "conflict_policy": conflict_policy,
                    "metadata": metadata or {},
                },
            ),
        )

    def delete_memory(self, record_id: str) -> None:
        headers = {
            "X-Arvectum-Consumer": self._consumer,
            "X-Arvectum-Consumer-Key": self._consumer_key,
        }
        self._request("DELETE", f"/v1/memory/{record_id}", headers=headers)

    def search(
        self,
        *,
        query: str,
        collections: list[str],
        limit: int,
        mode: str = "hybrid",
        lexical_weight: float = 1.0,
        vector_weight: float = 1.0,
        filters: dict[str, list[str]] | None = None,
        query_variants: list[str] | None = None,
        query_variant_weight: float = 0.5,
        expand_query: bool = False,
        query_expansion_limit: int = 4,
        collapse_by_canonical_uri: bool = False,
        rerank: bool = False,
        rerank_candidates: int = 20,
        rerank_strategy: str = "cross_encoder",
    ) -> list[SearchHit]:
        headers: dict[str, str] = {}
        if self._consumer or self._consumer_key:
            headers["X-Arvectum-Consumer"] = self._consumer
            headers["X-Arvectum-Consumer-Key"] = self._consumer_key
        payload = cast(
            SearchResponse,
            self.request_json(
                "POST",
                "/v1/search",
                headers=headers or None,
                json={
                    "query": query,
                    "collections": collections,
                    "filters": filters or {},
                    "limit": limit,
                    "mode": mode,
                    "lexical_weight": lexical_weight,
                    "vector_weight": vector_weight,
                    "query_variants": query_variants or [],
                    "query_variant_weight": query_variant_weight,
                    "expand_query": expand_query,
                    "query_expansion_limit": query_expansion_limit,
                    "collapse_by_canonical_uri": collapse_by_canonical_uri,
                    "rerank": rerank,
                    "rerank_candidates": rerank_candidates,
                    "rerank_strategy": rerank_strategy,
                },
            ),
        )
        hits = payload.get("hits", [])
        if not isinstance(hits, list):
            raise DataPlatformError(
                "Data Platform search returned invalid hits payload"
            )
        return [
            cast(SearchHit, item)
            for item in hits
            if isinstance(item, dict)
        ]

    def search_with_profile(
        self,
        *,
        query: str,
        collections: list[str],
        limit: int,
        profile: SearchProfile,
        filters: dict[str, list[str]] | None = None,
        query_variants: list[str] | None = None,
    ) -> list[SearchHit]:
        return self.search(
            query=query,
            collections=collections,
            limit=limit,
            mode=str(profile.get("mode", "hybrid")),
            lexical_weight=float(profile.get("lexical_weight", 1.0)),
            vector_weight=float(profile.get("vector_weight", 1.0)),
            filters=filters,
            query_variants=query_variants,
            query_variant_weight=float(profile.get("query_variant_weight", 0.5)),
            expand_query=bool(profile.get("expand_query", False)),
            query_expansion_limit=int(profile.get("query_expansion_limit", 4)),
            collapse_by_canonical_uri=bool(
                profile.get("collapse_by_canonical_uri", False)
            ),
            rerank=bool(profile.get("rerank", False)),
            rerank_candidates=int(profile.get("rerank_candidates", 20)),
            rerank_strategy=str(profile.get("rerank_strategy", "cross_encoder")),
        )

    def create_connector_credential(
        self,
        *,
        connector: str,
        secrets: dict[str, str],
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorCredential:
        return cast(
            ConnectorCredential,
            self.request_json(
                "POST",
                "/v1/connectors/credentials",
                headers=self._consumer_headers_required(),
                json={
                    "connector": connector,
                    "secrets": secrets,
                    "label": label,
                    "metadata": metadata or {},
                },
            ),
        )

    def list_connector_credentials(
        self,
        *,
        connector: str | None = None,
    ) -> list[ConnectorCredential]:
        params = {"connector": connector} if connector is not None else None
        return cast(
            list[ConnectorCredential],
            self.request_json(
                "GET",
                "/v1/connectors/credentials",
                headers=self._consumer_headers_required(),
                params=params,
            ),
        )

    def rotate_connector_credential(
        self,
        credential_id: str,
        *,
        secrets: dict[str, str],
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectorCredential:
        payload: dict[str, Any] = {
            "secrets": secrets,
            "label": label,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        return cast(
            ConnectorCredential,
            self.request_json(
                "POST",
                f"/v1/connectors/credentials/{credential_id}/rotate",
                headers=self._consumer_headers_required(),
                json=payload,
            ),
        )

    def revoke_connector_credential(
        self,
        credential_id: str,
    ) -> ConnectorCredential:
        return cast(
            ConnectorCredential,
            self.request_json(
                "POST",
                f"/v1/connectors/credentials/{credential_id}/revoke",
                headers=self._consumer_headers_required(),
            ),
        )

    def discover(
        self,
        *,
        connector: str,
        query: str,
        cursor: str | None = None,
        limit: int = 10,
        credential_id: str | None = None,
    ) -> DiscoveryResponse:
        payload: dict[str, Any] = {
            "connector": connector,
            "query": query,
            "limit": limit,
        }
        if cursor is not None:
            payload["cursor"] = cursor
        if credential_id is not None:
            payload["credential_id"] = credential_id
        headers = (
            {
                "X-Arvectum-Consumer": self._consumer,
                "X-Arvectum-Consumer-Key": self._consumer_key,
            }
            if self._consumer or self._consumer_key
            else None
        )
        return cast(
            DiscoveryResponse,
            self.request_json(
                "POST",
                "/v1/discover",
                headers=headers,
                json=payload,
            ),
        )

    def resolve_entity(
        self,
        *,
        entity_type: str,
        value: str,
        alias_kind: str = "name",
        limit: int = 20,
    ) -> EntityResolveResponse:
        return cast(
            EntityResolveResponse,
            self.request_json(
                "POST",
                "/v1/entities/resolve",
                json={
                    "entity_type": entity_type,
                    "value": value,
                    "alias_kind": alias_kind,
                    "limit": limit,
                },
            ),
        )

    def create_entity(
        self,
        *,
        entity_type: str,
        canonical_name: str,
        aliases: list[EntityAliasInput] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Entity:
        return cast(
            Entity,
            self.request_json(
                "POST",
                "/v1/entities",
                json={
                    "entity_type": entity_type,
                    "canonical_name": canonical_name,
                    "aliases": aliases or [],
                    "metadata": metadata or {},
                },
            ),
        )

    def create_entity_relation(
        self,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        source_collection_id: str | None = None,
        resource_id: str | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EntityRelation:
        payload: dict[str, Any] = {
            "source_entity_id": source_entity_id,
            "target_entity_id": target_entity_id,
            "relation_type": relation_type,
            "metadata": metadata or {},
        }
        for key, value in {
            "source_collection_id": source_collection_id,
            "resource_id": resource_id,
            "document_id": document_id,
            "chunk_id": chunk_id,
        }.items():
            if value is not None:
                payload[key] = value
        return cast(
            EntityRelation,
            self.request_json(
                "POST",
                "/v1/entity-relations",
                json=payload,
            ),
        )


DataPlatformHttpClient = DataPlatformClient
