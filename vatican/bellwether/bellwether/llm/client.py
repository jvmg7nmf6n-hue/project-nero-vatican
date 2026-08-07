"""Async Anthropic client.

Thin, dependency-light wrapper over the Messages API. Two ergonomic helpers:

  * complete()      -> assembled text from all text blocks
  * complete_json() -> parsed dict/list, tolerant of ```json fences

If no API key is configured, calls raise LLMUnavailable so agents can fall back
to deterministic heuristics — the whole engine still runs offline.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import Settings, get_settings

log = logging.getLogger("bellwether.llm")

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class LLMUnavailable(RuntimeError):
    """Raised when the LLM cannot be reached (no key, network, or API error)."""


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def available(self) -> bool:
        return self.settings.llm_available

    def _web_search_tool(self) -> dict[str, Any]:
        return {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": self.settings.web_search_max_uses,
        }

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        web_search: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        if not self.available:
            raise LLMUnavailable("No ANTHROPIC API key configured")

        body: dict[str, Any] = {
            "model": self.settings.llm_model,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        if web_search and self.settings.enable_web_search:
            body["tools"] = [self._web_search_tool()]

        headers = {
            "x-api-key": self.settings.anthropic_api_key or "",
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                resp = await client.post(API_URL, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:  # pragma: no cover - network
            log.warning("LLM call failed: %s", exc)
            raise LLMUnavailable(str(exc)) from exc

        # Assemble text from every text block (ignoring tool_use/tool_result).
        parts = [
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p).strip()

    async def complete_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        web_search: bool = False,
        max_tokens: int | None = None,
    ) -> Any:
        text = await self.complete(
            prompt,
            system=(system or "") + "\nRespond with ONLY valid JSON. No prose, no markdown fences.",
            web_search=web_search,
            max_tokens=max_tokens,
        )
        return _loads_lenient(text)


def _loads_lenient(text: str) -> Any:
    """Parse JSON even if the model wrapped it in fences or added stray prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # last resort: grab the outermost {...} or [...]
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = cleaned.find(open_c)
            end = cleaned.rfind(close_c)
            if start != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    continue
        raise LLMUnavailable("Could not parse JSON from LLM response")
