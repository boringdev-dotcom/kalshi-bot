"""Static configuration from the environment. Runtime settings live in the DB."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

KALSHI_HOSTS = {
    "prod": "https://api.elections.kalshi.com",
    "demo": "https://demo-api.kalshi.co",
}


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kalshi_api_key_id: str = ""
    kalshi_private_key_pem: str = ""
    kalshi_env: str = "prod"

    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_fast_model: str = "claude-haiku-5-5"

    odds_api_key: str = ""

    # Password for the web UI. Required when hosted; optional on your own machine.
    app_password: str = ""

    db_path: str = "data/courtside.db"
    paper_starting_cash: float = 5000.0

    @property
    def hosted(self) -> bool:
        """Running on a public host (Render sets RENDER=true) rather than a laptop."""
        return bool(os.environ.get("RENDER") or os.environ.get("COURTSIDE_HOSTED"))

    @property
    def env(self) -> str:
        return "demo" if self.kalshi_env.lower().startswith("demo") else "prod"

    @property
    def has_kalshi_keys(self) -> bool:
        return bool(self.kalshi_api_key_id.strip() and self.kalshi_private_key_pem.strip())

    @property
    def has_claude(self) -> bool:
        return bool(self.anthropic_api_key.strip() or self.anthropic_auth_token.strip())

    @property
    def has_odds(self) -> bool:
        return bool(self.odds_api_key.strip())

    @property
    def trading_host(self) -> str:
        return KALSHI_HOSTS[self.env]

    @property
    def private_key(self) -> str:
        return self.kalshi_private_key_pem.replace("\\n", "\n")


@lru_cache
def get_config() -> Config:
    return Config()
