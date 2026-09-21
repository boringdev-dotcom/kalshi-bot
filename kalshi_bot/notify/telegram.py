"""Telegram notifications and command polling."""

from __future__ import annotations

import logging
from typing import Callable, Optional

import httpx

from kalshi_bot.config import Settings
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self.offset: Optional[int] = None

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)
            return False

    def get_updates(self, timeout: int = 0) -> list[dict]:
        if not self.enabled:
            return []
        params: dict = {"timeout": timeout}
        if self.offset is not None:
            params["offset"] = self.offset
        try:
            with httpx.Client(timeout=timeout + 10) as client:
                response = client.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("Telegram getUpdates failed: %s", exc)
            return []
        updates = payload.get("result") or []
        for update in updates:
            self.offset = int(update["update_id"]) + 1
        return updates


def format_games(store: Store) -> str:
    upcoming = store.upcoming_games()
    live = store.live_games()
    if not upcoming and not live:
        return "No watched games in the next 6 hours."
    lines = []
    if live:
        lines.append("Live:")
        for game in live:
            lines.append(
                f"• {game['home_team']} {game.get('home_goals', 0)}-{game.get('away_goals', 0)} "
                f"{game['away_team']} {game.get('minute')}' {game.get('phase')}"
            )
    if upcoming:
        lines.append("Upcoming:")
        for game in upcoming:
            if game.get("status") == "live":
                continue
            lines.append(f"• {game['home_team']} vs {game['away_team']} ({game.get('league')})")
    return "\n".join(lines)


def format_held(store: Store) -> str:
    positions = store.open_positions()
    if not positions:
        return "No open positions."
    lines = ["Held:"]
    for pos in positions:
        mode = "paper" if pos.get("paper") else "live"
        lines.append(
            f"• {pos['market_ticker']} {pos['count']}x No @ {pos.get('avg_price')}¢ ({mode})"
        )
    return "\n".join(lines)


def format_status(store: Store, settings: Settings) -> str:
    return (
        f"paused={store.is_paused()}\n"
        f"paper={store.is_paper()}\n"
        f"kalshi_env={settings.kalshi_env}\n"
        f"model={settings.xai_model}\n"
        f"xai_configured={bool(settings.xai_api_key)}\n"
        f"live_games={len(store.live_games())}\n"
        f"open_positions={len(store.open_positions())}"
    )


def handle_command(store: Store, settings: Settings, text: str) -> Optional[str]:
    cmd = text.strip().split()[0].lower()
    if cmd == "/games":
        return format_games(store)
    if cmd == "/held":
        return format_held(store)
    if cmd == "/status":
        return format_status(store, settings)
    if cmd == "/pause":
        store.set_paused(True)
        return "Trading paused."
    if cmd == "/resume":
        store.set_paused(False)
        return "Trading resumed."
    return None


def poll_commands(notifier: TelegramNotifier, store: Store, settings: Settings) -> None:
    if not notifier.enabled:
        return
    for update in notifier.get_updates(timeout=0):
        message = update.get("message") or update.get("edited_message") or {}
        text = message.get("text") or ""
        if not text.startswith("/"):
            continue
        reply = handle_command(store, settings, text)
        if reply:
            notifier.send(reply)


def build_notifier(settings: Settings) -> TelegramNotifier:
    return TelegramNotifier(settings.telegram_bot_token or "", settings.telegram_chat_id or "")
