"""Provider-agnostic OpenAI-compatible chat client.

Works with OpenRouter, Ollama (``/v1`` compatibility layer), OpenAI and any
other OpenAI-compatible server (vLLM, LM Studio, llama.cpp, ...).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Endpoint

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(RuntimeError):
    """Raised when the upstream model returns an unusable response."""


def parse_json(text: str) -> Any:
    """Best-effort extraction of a JSON value from a model response."""
    text = (text or "").strip()
    if not text:
        raise LLMError("empty model response")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence = _FENCE_RE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    start_candidates = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if start_candidates:
        start = min(start_candidates)
        end = max(text.rfind("}"), text.rfind("]"))
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

    raise LLMError(f"could not parse JSON from model response: {text[:300]!r}")


class LLMClient:
    def __init__(
        self,
        endpoint: Endpoint,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout: float = 180.0,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(
            base_url=endpoint.base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {endpoint.api_key}", **endpoint.extra_headers},
        )

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"malformed chat response: {data}") from exc
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return content or ""

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
    ) -> Any:
        raw = await self.chat(
            messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        try:
            return parse_json(raw)
        except LLMError:
            # Some providers/models ignore response_format; retry with a hint.
            messages = [
                *messages,
                {
                    "role": "system",
                    "content": "Respond with valid JSON only. No prose, no markdown fences.",
                },
            ]
            raw = await self.chat(messages, temperature=temperature)
            return parse_json(raw)

    async def aclose(self) -> None:
        await self._client.aclose()
