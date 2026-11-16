"""Application settings: the only module that reads the environment (NFR-005, task T014).

Model IDs and the database URL have no defaults in code. Their defaults live in `.env.example`
only, so a missing value fails loudly instead of silently using a hard-coded model.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    # Models (research R3). Provider keys (e.g. GEMINI_API_KEY) are read by LiteLLM itself.
    llm_model: str
    llm_fast_model: str
    llm_judge_model: str
    embedding_model: str
    embedding_dim: int = Field(gt=0)

    # App
    database_url: str
    data_dir: Path = Path("/tmp/codecompass")  # noqa: S108 - overridden in compose
    max_files: int = 5000
    max_index_bytes: int = 50_000_000
    max_file_bytes: int = 524_288
    max_download_bytes: int = 200_000_000
    max_upload_bytes: int = 200_000_000
    max_archive_entries: int = 100_000
    max_uncompressed_bytes: int = 1_000_000_000
    embed_batch_size: int = 64
    embed_tokens_per_minute: int = Field(default=0, ge=0)  # 0 = no pacing (NFR-004)
    embed_rate_limit_retries: int = Field(default=5, ge=0)
    retrieval_top_k: int = 20
    context_max_chunks: int = 8
    context_max_tokens: int = 6000
    retrieval_min_score: float = 0.35
    github_api_base: str = "https://api.github.com"
    github_token: SecretStr | None = None
    llm_help_url: str = ""
    static_dir: Path = Path("/app/static")  # built SPA (Dockerfile copies frontend/dist here)

    # Langfuse (research R10)
    langfuse_enabled: bool = True
    langfuse_host: str = "http://localhost:3000"
    langfuse_ui_url: str = "http://localhost:3000"
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_project_id: str | None = None  # builds "Open in Langfuse" links (FR-040)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment
