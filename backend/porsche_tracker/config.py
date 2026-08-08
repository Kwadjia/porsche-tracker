"""Runtime configuration from environment / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Postgres (Neon in prod, local docker in dev)
    database_url: str = "postgresql+psycopg://porsche:porsche@localhost:5432/porsche"

    # eBay Browse API (free developer account -> client credentials)
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    ebay_marketplace: str = "EBAY_MOTORS"

    # Google Programmable Search (dealer discovery; 100 free queries/day)
    google_pse_key: str | None = None
    google_pse_cx: str | None = None

    # polite defaults for any direct HTTP fetching
    user_agent: str = "porsche-tracker/0.1 (personal research; +cars.arthurnemeth.com)"
    request_timeout_s: float = 20.0

    # geography for search targeting
    home_zip: str = "10001"


settings = Settings()
