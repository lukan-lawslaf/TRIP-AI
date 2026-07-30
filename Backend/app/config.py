"""Application settings.

Every secret and tunable lives here, loaded from `.env` via pydantic-settings.
Nothing else in the codebase reads `os.environ` directly.

Note: `Settings` never exposes a `__repr__` containing secret values — secrets are
typed `SecretStr` so an accidental log line prints `**********` instead of the key.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = parent of Backend/. The .env lives beside Backend/, not inside it.
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- app ----
    app_name: str = "TripAI Backend"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # ---- LLM provider keys (§7) ----
    open_router_api_key: SecretStr | None = None
    nvidia_nim_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    # Google AI Studio (Gemma/Gemini direct). `.env` uses GOOGLE_STUDIO_API_KEY;
    # the other two names are accepted because the official SDK looks for them.
    google_studio_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # ---- web search (orchestrator-facing, §4.1) ----
    web_search_api_key: SecretStr | None = None   # Serper — Google-style SERP results
    web2_search_api_key: SecretStr | None = None  # Tavily — synthesized answer + sources

    # ---- travel API keys (§7) ----
    flight_api_key: SecretStr | None = None           # Duffel
    flight_data_api_key: SecretStr | None = None      # secondary flight source
    hotel_api_key: SecretStr | None = None            # liteAPI
    weather_api_key: SecretStr | None = None          # OpenWeatherMap
    google_maps_demo_api_key: SecretStr | None = None # Google Maps
    locationiq_api_key: SecretStr | None = None      # LocationIQ geocoding/routing
    openrouteservice_api_key: SecretStr | None = None # openrouteservice routing
    restaurant_api_key: SecretStr | None = None       # Foursquare
    train_india_api_key: SecretStr | None = None      # RapidAPI / IRCTC
    train_demo_global_api_token: SecretStr | None = None  # Navitia

    # ---- storage ----
    # SQLite by default so the project runs with zero external services.
    # Swap to a postgresql:// URL and the schema layer follows (see storage/db.py).
    database_url: str = Field(default_factory=lambda: f"sqlite:///{DATA_DIR / 'tripai.db'}")
    chroma_dir: Path = Field(default_factory=lambda: DATA_DIR / "chroma")
    upload_dir: Path = Field(default_factory=lambda: DATA_DIR / "uploads")
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # ---- cache ----
    redis_url: str | None = Field(default="redis://localhost:6379/0")
    cache_enabled: bool = True
    # TTLs in seconds (§8): places/maps = days, weather = hours.
    cache_ttl_places: int = 60 * 60 * 24 * 3
    cache_ttl_maps: int = 60 * 60 * 24 * 3
    cache_ttl_weather: int = 60 * 60 * 3
    cache_ttl_flights: int = 60 * 15
    cache_ttl_hotels: int = 60 * 30

    # ---- resilience (§3.3, §8) ----
    llm_timeout_seconds: float = 90.0
    tool_timeout_seconds: float = 20.0
    tool_retries: int = 1
    breaker_failure_threshold: int = 3      # consecutive failures before opening
    breaker_window_seconds: float = 120.0   # failures older than this are forgotten
    breaker_cooldown_seconds: float = 300.0 # how long a candidate stays skipped

    # ---- conversation (§6) ----
    raw_turns_in_context: int = 6           # last N raw turns sent verbatim
    summarize_after_turns: int = 10         # aggressive summarization past this
    context_token_budget: int = 12_000      # tripwire → summarize before appending

    # ---- uploads ----
    max_upload_bytes: int = 20 * 1024 * 1024
    max_uploads_per_message: int = 4

    @property
    def google_ai_studio_key(self) -> SecretStr | None:
        """Google AI Studio accepts any of these env names; `.env` uses the first."""
        return (
            self.google_studio_api_key or self.google_api_key or self.gemini_api_key
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings
