"""Provider-agnostic OpenAI-compatible embedding client."""

from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Endpoint


class EmbeddingClient:
    def __init__(
        self,
        endpoint: Endpoint,
        model: str,
        dim: int = 768,
        batch_size: int = 64,
        timeout: float = 120.0,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.dim = dim
        self.batch_size = max(1, batch_size)
        self._client = httpx.AsyncClient(
            base_url=endpoint.base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {endpoint.api_key}"},
        )

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            "/embeddings",
            json={"model": self.model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        items = sorted(data["data"], key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in items]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(await self._embed_batch(texts[start : start + self.batch_size]))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed([text])
        return vectors[0]

    async def aclose(self) -> None:
        await self._client.aclose()
