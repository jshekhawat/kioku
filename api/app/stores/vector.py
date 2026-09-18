"""Qdrant-backed vector store for memories."""

from __future__ import annotations

import logging
from typing import Any

from qdrant_client import AsyncQdrantClient, models

logger = logging.getLogger(__name__)

SCOPE_FIELDS = ("user_id", "agent_id", "run_id")
INDEXED_FIELDS = (*SCOPE_FIELDS, "hash")


class VectorStore:
    def __init__(
        self,
        url: str,
        collection: str,
        dim: int,
        api_key: str | None = None,
    ) -> None:
        self.collection = collection
        self.dim = dim
        self.client = AsyncQdrantClient(
            url=url, api_key=api_key or None, check_compatibility=False
        )

    async def ensure_collection(self) -> None:
        exists = await self.client.collection_exists(self.collection)
        if not exists:
            await self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=self.dim,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info("created qdrant collection %s (dim=%d)", self.collection, self.dim)

        for field in INDEXED_FIELDS:
            try:
                await self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception as exc:  # index already exists / race
                logger.debug("payload index %s skipped: %s", field, exc)

    @staticmethod
    def _scope_filter(scope: dict[str, str | None]) -> models.Filter | None:
        must = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in scope.items()
            if key in SCOPE_FIELDS and value
        ]
        return models.Filter(must=must) if must else None

    async def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        await self.client.upsert(
            collection_name=self.collection,
            points=[models.PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    async def exists_hash(self, hash_value: str, scope: dict[str, str | None]) -> bool:
        conditions = [
            models.FieldCondition(key="hash", match=models.MatchValue(value=hash_value))
        ]
        conditions.extend(
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in scope.items()
            if key in SCOPE_FIELDS and value
        )
        result = await self.client.count(
            collection_name=self.collection,
            count_filter=models.Filter(must=conditions),
            exact=True,
        )
        return result.count > 0

    async def search(
        self,
        vector: list[float],
        scope: dict[str, str | None],
        limit: int,
        score_threshold: float | None = None,
    ) -> list[models.ScoredPoint]:
        response = await self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=self._scope_filter(scope),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return list(response.points)

    async def retrieve(self, point_ids: list[str]) -> list[models.Record]:
        if not point_ids:
            return []
        return await self.client.retrieve(
            collection_name=self.collection,
            ids=point_ids,
            with_payload=True,
        )

    async def scroll(
        self,
        scope: dict[str, str | None],
        limit: int = 100,
    ) -> list[models.Record]:
        records, _ = await self.client.scroll(
            collection_name=self.collection,
            scroll_filter=self._scope_filter(scope),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return list(records)

    async def update_payload(self, point_id: str, payload: dict[str, Any]) -> None:
        await self.client.set_payload(
            collection_name=self.collection,
            payload=payload,
            points=[point_id],
        )

    async def delete(self, point_ids: list[str]) -> int:
        if not point_ids:
            return 0
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(points=point_ids),
        )
        return len(point_ids)

    async def delete_scope(self, scope: dict[str, str | None]) -> int:
        scroll_filter = self._scope_filter(scope)
        if scroll_filter is None:
            raise ValueError("delete_scope requires at least one scope id")
        count = await self.client.count(
            collection_name=self.collection,
            count_filter=scroll_filter,
            exact=True,
        )
        if count.count == 0:
            return 0
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(filter=scroll_filter),
        )
        return count.count

    async def aclose(self) -> None:
        await self.client.close()
