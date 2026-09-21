"""xAI Grok chat completions with tool calling and cost logging."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from kalshi_bot.config import Settings
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)


class GrokError(RuntimeError):
    pass


def estimate_cost(settings: Settings, input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000 * settings.xai_input_price_per_mtok
        + output_tokens / 1_000_000 * settings.xai_output_price_per_mtok
    )


class GrokClient:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    def available(self) -> bool:
        return bool(self.settings.xai_api_key)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        agent: str,
        game_id: Optional[str] = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not self.settings.xai_api_key:
            raise GrokError("XAI_API_KEY is not set")
        body: dict[str, Any] = {
            "model": self.settings.xai_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self.settings.xai_api_key}",
            "Content-Type": "application/json",
        }
        url = self.settings.xai_base_url.rstrip("/") + "/chat/completions"
        with httpx.Client(timeout=90.0) as client:
            response = client.post(url, headers=headers, json=body)
            if response.status_code >= 400:
                raise GrokError(f"xAI {response.status_code}: {response.text[:400]}")
            data = response.json()
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        cost = estimate_cost(self.settings, input_tokens, output_tokens)
        self.store.add_llm_cost(
            agent=agent,
            model=self.settings.xai_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            game_id=game_id,
        )
        logger.info(
            "Grok %s model=%s in=%s out=%s cost=$%.6f",
            agent,
            self.settings.xai_model,
            input_tokens,
            output_tokens,
            cost,
        )
        return data


def message_content(message: dict[str, Any]) -> str:
    content = message.get("content") or ""
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content)


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise
