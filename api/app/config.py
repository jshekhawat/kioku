"""Application configuration, loaded from environment variables.

All settings are prefixed with ``KIOKU_`` (e.g. ``KIOKU_LLM_MODEL``).
A ``.env`` file in the working directory is loaded automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Endpoint:
    """A resolved OpenAI-compatible endpoint."""

    base_url: str
    api_key: str
    extra_headers: dict[str, str]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KIOKU_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Chat / completion model -------------------------------------------
    llm_provider: str = "openrouter"  # openrouter | ollama | openai
    llm_model: str = "openai/gpt-4o-mini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048

    # --- Embedding model ----------------------------------------------------
    embed_provider: str = "ollama"  # ollama | openrouter | openai
    embed_model: str = "nomic-embed-text"
    embed_base_url: str | None = None
    embed_api_key: str | None = None
    embed_dim: int = 768
    embed_batch_size: int = 64

    # --- OpenRouter ---------------------------------------------------------
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_referer: str | None = None
    openrouter_title: str = "kioku"

    # --- Ollama -------------------------------------------------------------
    ollama_base_url: str = "http://ollama:11434"

    # --- Qdrant -------------------------------------------------------------
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "kioku_memories"
    qdrant_recreate_on_dim_mismatch: bool = False

    # --- Knowledge graph ----------------------------------------------------
    graph_enabled: bool = True
    falkordb_host: str = "falkordb"
    falkordb_port: int = 6379
    falkordb_graph: str = "kioku"

    # --- Behaviour ----------------------------------------------------------
    default_search_limit: int = 10
    similarity_threshold: float = 0.1
    log_level: str = "INFO"

    # --- Servers ------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8090

    def llm_endpoint(self) -> Endpoint:
        provider = self.llm_provider.lower().strip()
        if provider == "ollama":
            return Endpoint(
                base_url=self.llm_base_url or f"{self.ollama_base_url.rstrip('/')}/v1",
                api_key=self.llm_api_key or "ollama",
                extra_headers={},
            )
        if provider == "openrouter":
            key = self.llm_api_key or self.openrouter_api_key or ""
            headers: dict[str, str] = {}
            if self.openrouter_referer:
                headers["HTTP-Referer"] = self.openrouter_referer
            if self.openrouter_title:
                headers["X-Title"] = self.openrouter_title
            return Endpoint(self.llm_base_url or self.openrouter_base_url, key, headers)
        if provider in {"openai", "custom", "openai-compatible"}:
            return Endpoint(
                base_url=self.llm_base_url or "https://api.openai.com/v1",
                api_key=self.llm_api_key or "",
                extra_headers={},
            )
        raise ValueError(f"Unknown LLM provider: {self.llm_provider!r}")

    def embed_endpoint(self) -> Endpoint:
        provider = self.embed_provider.lower().strip()
        if provider == "ollama":
            return Endpoint(
                base_url=self.embed_base_url or f"{self.ollama_base_url.rstrip('/')}/v1",
                api_key=self.embed_api_key or "ollama",
                extra_headers={},
            )
        if provider == "openrouter":
            return Endpoint(
                base_url=self.embed_base_url or self.openrouter_base_url,
                api_key=self.embed_api_key or self.openrouter_api_key or "",
                extra_headers={},
            )
        if provider in {"openai", "custom", "openai-compatible"}:
            return Endpoint(
                base_url=self.embed_base_url or "https://api.openai.com/v1",
                api_key=self.embed_api_key or "",
                extra_headers={},
            )
        raise ValueError(f"Unknown embedding provider: {self.embed_provider!r}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
