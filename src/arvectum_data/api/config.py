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
    max_upload_bytes: int = Field(default=10_000_000, ge=1)
    max_chunks_per_ingest: int = Field(default=1000, ge=1)
    max_search_collections: int = Field(default=32, ge=1)
    allow_private_fetches: bool = False

    embedding_provider: str = "hashing"
    embedding_model: str = "local-hash-v1"
    embedding_base_url: str = "http://127.0.0.1:8090/v1"
    embedding_timeout_seconds: int = 60
    embedding_dimension: str | int | None = 256

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
