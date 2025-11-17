"""Configuration management for Kalshi Discord bot."""
import os
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Kalshi API credentials
    kalshi_api_key_id: Optional[str] = Field(default=None, alias="KALSHI_API_KEY_ID")
    kalshi_private_key_pem: Optional[str] = Field(default=None, alias="KALSHI_PRIVATE_KEY_PEM")
    kalshi_ws_url: str = Field(
        default="wss://demo-api.kalshi.co/trade-api/ws/v2",
        alias="KALSHI_WS_URL"
    )
    
    # Discord configuration
    discord_bot_token: Optional[str] = Field(default=None, alias="DISCORD_BOT_TOKEN")
    discord_channel_id: Optional[str] = Field(default=None, alias="DISCORD_CHANNEL_ID")
    discord_webhook_url: Optional[str] = Field(default=None, alias="DISCORD_WEBHOOK_URL")
    
    # API server configuration
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    
    @field_validator("kalshi_private_key_pem", mode="before")
    @classmethod
    def normalize_private_key(cls, v: Optional[str]) -> Optional[str]:
        """Normalize private key by replacing \\n with actual newlines."""
        if v:
            return v.replace("\\n", "\n")
        return v
    
    @property
    def use_discord_bot(self) -> bool:
        """Check if Discord bot should be used (requires both token and channel ID)."""
        return bool(self.discord_bot_token and self.discord_channel_id)
    
    @property
    def discord_channel_id_int(self) -> Optional[int]:
        """Get Discord channel ID as integer."""
        if self.discord_channel_id:
            try:
                return int(self.discord_channel_id)
            except ValueError:
                return None
        return None
    
    def validate_required(self) -> list[str]:
        """
        Validate required settings and return list of missing variables.
        
        Returns:
            List of missing required environment variable names.
        """
        missing = []
        
        if not self.kalshi_api_key_id:
            missing.append("KALSHI_API_KEY_ID")
        if not self.kalshi_private_key_pem:
            missing.append("KALSHI_PRIVATE_KEY_PEM")
        
        # Require either Discord bot OR webhook
        if not self.use_discord_bot and not self.discord_webhook_url:
            missing.append("DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID (or DISCORD_WEBHOOK_URL)")
        
        return missing
    
    def get_api_base_url(self) -> str:
        """Get Kalshi API base URL based on WebSocket URL."""
        if "demo" in self.kalshi_ws_url:
            return "https://demo-api.kalshi.co"
        return "https://api.elections.kalshi.com"
    
    def get_website_base_url(self) -> str:
        """Get Kalshi website base URL based on WebSocket URL."""
        if "demo" in self.kalshi_ws_url:
            return "https://demo.kalshi.co"
        return "https://kalshi.com"

