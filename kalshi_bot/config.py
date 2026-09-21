"""Environment-backed settings."""

from __future__ import annotations

import os
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    kalshi_api_key_id: Optional[str] = Field(default=None, alias="KALSHI_API_KEY_ID")
    kalshi_private_key_pem: Optional[str] = Field(default=None, alias="KALSHI_PRIVATE_KEY_PEM")
    kalshi_env: str = Field(default="demo", alias="KALSHI_ENV")
    kalshi_api_base_url: Optional[str] = Field(default=None, alias="KALSHI_API_BASE_URL")
    kalshi_ws_url: Optional[str] = Field(default=None, alias="KALSHI_WS_URL")

    paper_mode: bool = Field(default=True, alias="PAPER_MODE")
    trading_paused: bool = Field(default=False, alias="TRADING_PAUSED")

    xai_api_key: Optional[str] = Field(default=None, alias="XAI_API_KEY")
    xai_model: str = Field(default="grok-4-1-fast", alias="XAI_MODEL")
    xai_base_url: str = Field(default="https://api.x.ai/v1", alias="XAI_BASE_URL")
    xai_input_price_per_mtok: float = Field(default=0.20, alias="XAI_INPUT_PRICE_PER_MTOK")
    xai_output_price_per_mtok: float = Field(default=0.50, alias="XAI_OUTPUT_PRICE_PER_MTOK")

    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")

    sqlite_path: str = Field(default="data/kalshi_bot.sqlite", alias="SQLITE_PATH")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    discovery_interval_sec: int = Field(default=1800, alias="DISCOVERY_INTERVAL_SEC")
    poll_interval_sec: int = Field(default=15, alias="POLL_INTERVAL_SEC")
    prematch_lead_sec: int = Field(default=900, alias="PREMATCH_LEAD_SEC")
    watch_horizon_hours: int = Field(default=6, alias="WATCH_HORIZON_HOURS")

    @field_validator("kalshi_private_key_pem", mode="before")
    @classmethod
    def normalize_private_key(cls, value: Optional[str]) -> Optional[str]:
        if value:
            return value.replace("\\n", "\n")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def use_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def use_demo(self) -> bool:
        env = (self.kalshi_env or "demo").lower()
        if self.kalshi_api_base_url:
            return "demo" in self.kalshi_api_base_url
        return env != "prod"

    def get_port(self) -> int:
        return int(os.environ.get("PORT", self.api_port))

    def api_base_url(self) -> str:
        if self.kalshi_api_base_url:
            return self.kalshi_api_base_url.rstrip("/")
        if self.use_demo:
            return "https://demo-api.kalshi.co"
        return "https://api.elections.kalshi.com"

    def ws_url(self) -> str:
        if self.kalshi_ws_url:
            return self.kalshi_ws_url
        host = self.api_base_url().split("://", 1)[-1]
        return f"wss://{host}/trade-api/ws/v2"

    def website_base_url(self) -> str:
        return "https://demo.kalshi.co" if self.use_demo else "https://kalshi.com"
