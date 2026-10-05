from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARVECTUM_DATA_",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "arvectum-data"
    environment: str = "development"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8088

    database_url: str = ""
    internal_api_key: str = ""
    consumer_api_keys: dict[str, str] = Field(default_factory=dict)
    max_upload_bytes: int = Field(default=10_000_000, ge=1)
    max_chunks_per_ingest: int = Field(default=1000, ge=1)
    max_search_collections: int = Field(default=32, ge=1)
    allow_private_fetches: bool = False

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

    ocr_provider: str = "disabled"
    ocr_languages: str = "rus+eng"
    ocr_dpi: int = Field(default=220, ge=72, le=600)
    ocr_timeout_seconds: float = Field(default=45, gt=0, le=300)

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
