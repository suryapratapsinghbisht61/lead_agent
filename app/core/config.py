"""All settings in one place.

Values come from environment variables / the .env file. Every other module
calls get_settings() instead of reading os.environ directly.
"""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two folders up from this file (app/core/config.py -> project/)
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Read .env from the project root; ignore unknown variables in it.
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    # --- LLM ---
    llm_provider: str = "google_genai"  # any provider init_chat_model supports
    llm_model: str = "gemini-3.5-flash-lite"
    # Tried in order when the main model's (daily) quota runs out. Comma-separated, same provider.
    llm_fallback_models: str = "gemini-3.1-flash-lite,gemini-3.6-flash,gemini-3.5-flash"
    llm_requests_per_minute: int = 10
    google_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # --- Bright Data ---
    brightdata_api_token: str | None = None
    brightdata_serp_zone: str = "sdk_serp"
    brightdata_unlocker_zone: str = "sdk_unlocker"
    max_credits_per_run: int = 200

    # --- Cache ---
    cache_dir: Path = ROOT_DIR / ".cache"
    cache_ttl_hours: int = 72

    # --- Storage / output ---
    database_url: str = f"sqlite:///{ROOT_DIR / 'data' / 'leads.db'}"
    export_dir: Path = ROOT_DIR / "exports"

    # --- Agent behaviour ---
    min_fit_score: int = 6  # leads scoring below this are saved as "low fit" and hidden
    max_search_rounds: int = 4  # how many times the agent may search again for more leads
    max_concurrency: int = 4  # leads researched in parallel
    log_level: str = "INFO"
    demo_mode: bool = False  # true = fake LLM + fake search results everywhere (try it without API keys)

    # --- Dashboard login: "id:password,id2:password2" (keep it out of the code; repo is public) ---
    dashboard_users: str = ""

    # --- Web app stage (API + worker) ---
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_per_minute: int = 60  # API requests per key per minute
    runs_per_hour: int = 10  # POST /runs per key per hour (each run costs credits)
    cors_origins: str = "http://localhost:3000,http://localhost:5173"  # comma-separated


    @field_validator("database_url", mode="before")
    @classmethod
    def _default_if_empty(cls, v):
        """An empty DATABASE_URL (e.g. left blank on Render) means 'use the local SQLite file'."""
        return v or f"sqlite:///{ROOT_DIR / 'data' / 'leads.db'}"


@lru_cache  # build Settings once, reuse everywhere
def get_settings() -> Settings:
    return Settings()


@lru_cache
def load_profile(path: Path = ROOT_DIR / "config" / "services.yaml") -> dict:
    """Load 'who I am / what I sell / who I target' from config/services.yaml."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
