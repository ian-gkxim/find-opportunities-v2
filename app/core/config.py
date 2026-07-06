"""Application configuration loaded from environment variables.

Requirement 18.6: Store credentials securely (environment variables or encrypted store).
All sensitive values are loaded exclusively from environment variables.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "GKIM Opportunity Finder v2"
    app_env: str = "development"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gkim_v2"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Apollo.io
    apollo_api_key: str = ""

    # Lemlist
    lemlist_api_key: str = ""

    # Adzuna
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    # Gmail / Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # LLM Providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # LLM Configuration
    llm_default_provider: str = "anthropic"
    llm_matching_model: str = "claude-sonnet-4-20250514"
    llm_generation_model: str = "claude-sonnet-4-20250514"

    # Schema
    schema_path: str = "config/schema.yaml"

    # Worker settings
    worker_enrichment_interval: int = 3600  # 1 hour
    worker_polling_interval: int = 300  # 5 minutes
    worker_analytics_cron: str = "0 2 * * *"  # 02:00 UTC daily

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Factory function for settings singleton."""
    return Settings()
