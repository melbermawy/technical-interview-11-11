"""Typed settings configuration - single source of truth."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str | None = None
    postgres_url: str = "postgresql://user:pass@localhost:5432/travel_planner"

    # Cache
    redis_url: str | None = None

    # UI
    ui_origin: str = "http://localhost:8501"

    # Auth
    jwt_private_key_pem: str = ""
    jwt_public_key_pem: str = ""

    # External APIs
    weather_api_key: str = ""

    # Graph orchestration
    fanout_cap: int = 4

    # Timing buffers (minutes)
    airport_buffer_min: int = 120
    transit_buffer_min: int = 15

    # Cache TTLs (hours)
    fx_ttl_hours: int = 24
    weather_ttl_hours: int = 24

    # Eval reproducibility
    eval_rng_seed: int = 42

    # Timeouts (milliseconds)
    tool_soft_timeout_ms: int = 2000
    tool_hard_timeout_ms: int = 4000

    # Retry jitter (milliseconds)
    retry_jitter_min_ms: int = 200
    retry_jitter_max_ms: int = 500

    # Circuit breaker
    circuit_breaker_failures: int = 5
    circuit_breaker_window_sec: int = 60

    # Performance budgets (milliseconds)
    ttfe_budget_ms: int = 800
    e2e_p50_budget_ms: int = 6000
    e2e_p95_budget_ms: int = 10000

    # Rate limiting (requests per minute)
    agent_runs_per_min: int = 5
    crud_ops_per_min: int = 60

    # Idempotency TTL (seconds)
    idempotency_ttl_seconds: int = 24 * 3600


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
