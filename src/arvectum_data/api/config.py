from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _loopback_host(value: str) -> bool:
    cleaned = value.strip().lower()
    if cleaned == "localhost":
        return True
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except ValueError:
        return False


def _url_is_local(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned:
        return True
    parsed = urlsplit(cleaned)
    if parsed.scheme.startswith("sqlite"):
        return True
    return _loopback_host(parsed.hostname or "")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARVECTUM_DATA_",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "arvectum-data"
    environment: str = "development"
    log_level: str = "INFO"
    deployment_mode: str = "standard"
    host: str = "127.0.0.1"
    port: int = 8088

    database_url: str = ""
    internal_api_key: str = ""
    consumer_api_keys: dict[str, str] = Field(default_factory=dict)
    consumer_tenants: dict[str, str] = Field(default_factory=dict)
    tenant_quotas: dict[str, dict[str, int]] = Field(default_factory=dict)
    max_upload_bytes: int = Field(default=10_000_000, ge=1)
    max_chunks_per_ingest: int = Field(default=1000, ge=1)
    max_search_collections: int = Field(default=32, ge=1)
    allow_private_fetches: bool = False
    connector_credentials_master_key: str = ""
    connector_credentials_key_version: str = "v1"

    embedding_provider: str = "hashing"
    embedding_model: str = "local-hash-v1"
    embedding_base_url: str = "http://127.0.0.1:8090/v1"
    embedding_timeout_seconds: int = 60
    embedding_dimension: str | int | None = 256
    embedding_retry_max_attempts: int = Field(default=3, ge=1, le=10)
    embedding_retry_base_delay_seconds: float = Field(default=0.25, ge=0.0)
    embedding_retry_max_delay_seconds: float = Field(default=2.0, ge=0.0)

    reasoning_policy: str = "disabled"
    reasoning_provider: str = "openai-compatible"
    reasoning_model: str = ""
    reasoning_model_version: str = ""
    reasoning_base_url: str = "http://127.0.0.1:8080/v1"
    reasoning_locality: str = "local"
    reasoning_remote_allowlist: str = ""
    reasoning_api_key: str = ""
    vision_policy: str = "disabled"
    vision_provider: str = "openai-compatible"
    vision_model: str = ""
    vision_model_version: str = ""
    vision_base_url: str = "http://127.0.0.1:8081/v1"
    vision_locality: str = "local"
    vision_remote_allowlist: str = ""
    vision_api_key: str = ""
    model_timeout_seconds: float = Field(default=60, gt=0)
    model_retry_max_attempts: int = Field(default=2, ge=1, le=10)
    model_retry_base_delay_seconds: float = Field(default=0.25, ge=0)
    model_max_concurrency: int = Field(default=2, ge=1, le=128)

    cross_encoder_provider: str = "http"
    cross_encoder_model: str = "BAAI/bge-reranker-v2-m3"
    cross_encoder_base_url: str = "http://127.0.0.1:8091"
    cross_encoder_timeout_seconds: float = Field(default=1.0, gt=0, le=30)
    cross_encoder_max_candidates: int = Field(default=3, ge=1, le=20)
    cross_encoder_max_candidate_chars: int = Field(default=1000, ge=128, le=8000)

    ocr_provider: str = "disabled"
    ocr_languages: str = "rus+eng"
    ocr_dpi: int = Field(default=220, ge=72, le=600)
    ocr_timeout_seconds: float = Field(default=45, gt=0, le=300)

    @model_validator(mode="after")
    def validate_deployment_privacy(self):
        cross_encoder_provider = self.cross_encoder_provider.strip().lower()
        if cross_encoder_provider not in {"disabled", "http", "sentence_transformers"}:
            raise ValueError(
                "cross_encoder_provider must be disabled, http or sentence_transformers"
            )
        self.cross_encoder_provider = cross_encoder_provider

        mode = self.deployment_mode.strip().lower()
        if mode not in {"standard", "local-private"}:
            raise ValueError("deployment_mode must be standard or local-private")
        self.deployment_mode = mode
        if mode != "local-private":
            return self

        violations: list[str] = []
        if not _loopback_host(self.host):
            violations.append("API host must be loopback")
        if self.database_url and not _url_is_local(self.database_url):
            violations.append("database_url must be local")
        embedding_provider = self.embedding_provider.strip().lower()
        if (
            embedding_provider not in {"hashing", "sentence_transformers"}
            and not _url_is_local(self.embedding_base_url)
        ):
            violations.append("embedding endpoint must be loopback")
        if self.ocr_provider.strip().lower() not in {"disabled", "tesseract"}:
            violations.append("OCR provider must be local or disabled")
        cross_encoder_provider = self.cross_encoder_provider.strip().lower()
        if cross_encoder_provider == "http" and not _url_is_local(self.cross_encoder_base_url):
            violations.append("cross-encoder endpoint must be loopback")

        for role in ("reasoning", "vision"):
            policy = str(getattr(self, f"{role}_policy")).strip().lower()
            locality = str(getattr(self, f"{role}_locality")).strip().lower()
            base_url = str(getattr(self, f"{role}_base_url"))
            allowlist = str(getattr(self, f"{role}_remote_allowlist")).strip()
            if policy not in {"disabled", "local-only"}:
                violations.append(f"{role} policy must be disabled or local-only")
            if policy == "local-only" and (
                locality != "local" or not _url_is_local(base_url)
            ):
                violations.append(f"{role} local-only endpoint must be loopback")
            if allowlist:
                violations.append(f"{role} remote allowlist must be empty")

        if violations:
            raise ValueError(
                "local-private deployment rejects configuration: "
                + "; ".join(violations)
            )
        return self

    @property
    def embeddings_provider(self) -> str:
        return self.embedding_provider

    @property
    def embeddings_model(self) -> str:
        return self.embedding_model

    @property
    def embeddings_base_url(self) -> str:
        return self.embedding_base_url

    @property
    def embeddings_timeout_seconds(self) -> int:
        return self.embedding_timeout_seconds
