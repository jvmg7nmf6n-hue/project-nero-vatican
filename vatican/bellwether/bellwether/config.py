"""Configuration management.

All runtime knobs live here and are overridable via environment variables or a
.env file. Nothing in the engine reads os.environ directly — they read settings.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELLWETHER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    # If no API key is present the engine runs in heuristic mode (no network).
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 1500
    llm_timeout_seconds: float = 60.0
    enable_web_search: bool = True
    # Hard ceiling on web_search tool invocations per agent call.
    web_search_max_uses: int = 5

    # --- Data providers ---
    # "mock" runs fully offline with realistic synthetic feeds.
    # "live" expects real provider implementations + credentials.
    data_mode: str = "mock"

    # --- Engine behaviour ---
    # Random seed makes mock runs reproducible for tests/backtests.
    seed: int = 42
    # Minimum confidence below which the trade engine returns NEUTRAL.
    min_actionable_confidence: float = 0.35
    # Where the learning store persists predictions + realized outcomes.
    store_path: str = "./.bellwether_store.json"

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @property
    def llm_available(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
