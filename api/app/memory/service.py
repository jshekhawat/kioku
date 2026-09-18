"""The memory pipeline: extraction, dedup, consolidation and retrieval."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.clients.embeddings import EmbeddingClient
from app.clients.llm import LLMClient, LLMError
from app.memory import prompts
from app.stores.graph import GraphStore
from app.stores.vector import VectorStore

logger = logging.getLogger(__name__)

_VALID_EVENTS = {"ADD", "UPDATE", "DELETE", "NONE"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class MemoryService:
    def __init__(
        self,
        *,
        llm: LLMClient,
        embeddings: EmbeddingClient,
        vector: VectorStore,
        graph: GraphStore | None,
        similarity_threshold: float = 0.1,
        default_limit: int = 10,
    ) -> None:
        self.llm = llm
        self.embeddings = embeddings
        self.vector = vector
        self.graph = graph
        self.similarity_threshold = similarity_threshold
        self.default_limit = default_limit

    # ------------------------------------------------------------------ add
    async def add(
        self,
        *,
        messages: list[dict[str, str]] | str,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        infer: bool = True,
    ) -> list[dict[str, Any]]:
        metadata = metadata or {}
        convo = self._normalize(messages)
        scope = self._scope(user_id, agent_id, run_id)

        if infer:
            facts = await self._extract_facts(convo)
        else:
            facts = [turn["content"] for turn in convo if turn.get("content")]

        results: list[dict[str, Any]] = []
        for fact in facts:
            result = await self._consolidate(
                fact, scope=scope, metadata=metadata
            )
            if result is not None:
                results.append(result)
        return results

    async def _consolidate(
        self,
        fact: str,
        *,
        scope: dict[str, str | None],
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        fact = fact.strip()
        if not fact:
            return None

        if await self.vector.exists_hash(_hash(fact), scope):
            return {"id": "", "memory": fact, "event": "NONE", "previous": None}

        vector = await self.embeddings.embed_one(fact)
        similar = await self.vector.search(
            vector, scope, limit=5, score_threshold=self.similarity_threshold
        )
        existing = [
            {"id": str(point.id), "memory": (point.payload or {}).get("memory", "")}
            for point in similar
        ]

        decision = await self._decide(fact, existing)
        event = str(decision.get("event", "ADD")).upper()
        if event not in _VALID_EVENTS:
            event = "ADD"
        if event == "NONE":
            return {"id": "", "memory": fact, "event": "NONE", "previous": None}

        target_id = decision.get("id")
        valid_ids = {item["id"] for item in existing}

        if event == "DELETE" and target_id in valid_ids:
            previous = next(item["memory"] for item in existing if item["id"] == target_id)
            await self.vector.delete([target_id])
            if self.graph:
                await self.graph.delete_memory(target_id)
            return {"id": target_id, "memory": fact, "event": "DELETE", "previous": previous}

        if event == "UPDATE" and target_id in valid_ids:
            final_text = (decision.get("text") or fact).strip() or fact
            previous = next(item["memory"] for item in existing if item["id"] == target_id)
            await self._write(target_id, final_text, scope, metadata, created_at=None)
            return {
                "id": target_id,
                "memory": final_text,
                "event": "UPDATE",
                "previous": previous,
            }

        memory_id = str(uuid4())
        await self._write(memory_id, fact, scope, metadata)
        return {"id": memory_id, "memory": fact, "event": "ADD", "previous": None}

    async def _write(
        self,
        memory_id: str,
        text: str,
        scope: dict[str, str | None],
        metadata: dict[str, Any],
        created_at: str | None = None,
    ) -> None:
        now = _now()
        payload = {
            "memory": text,
            "hash": _hash(text),
            "user_id": scope.get("user_id"),
            "agent_id": scope.get("agent_id"),
            "run_id": scope.get("run_id"),
            "metadata": metadata,
            "created_at": created_at or now,
            "updated_at": now,
        }
        vector = await self.embeddings.embed_one(text)
        await self.vector.upsert(memory_id, vector, payload)

        if self.graph:
            entities, relations = await self._extract_graph(text)
            await self.graph.upsert_memory(
                {"id": memory_id, **payload}, entities, relations
            )

    # --------------------------------------------------------------- search
    async def search(
        self,
        *,
        query: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        limit: int | None = None,
        threshold: float | None = None,
        use_graph: bool | None = None,
    ) -> list[dict[str, Any]]:
        limit = limit or self.default_limit
        threshold = self.similarity_threshold if threshold is None else threshold
        scope = self._scope(user_id, agent_id, run_id)

        vector = await self.embeddings.embed_one(query)
        hits = await self.vector.search(vector, scope, limit, score_threshold=threshold)

        results: dict[str, dict[str, Any]] = {}
        for point in hits:
            record = self._to_memory(str(point.id), point.payload or {})
            record["score"] = float(point.score)
            record["source"] = "vector"
            results[record["id"]] = record

        graph_enabled = self.graph is not None and (use_graph is not False)
        if graph_enabled and user_id:
            names = await self._extract_entity_names(query)
            graph_ids = await self.graph.related_memory_ids(names, user_id, limit=limit)
            missing = [mid for mid in graph_ids if mid not in results]
            for record in await self.vector.retrieve(missing):
                payload = record.payload or {}
                if not self._in_scope(payload, scope):
                    continue
                item = self._to_memory(str(record.id), payload)
                item["score"] = None
                item["source"] = "graph"
                results[item["id"]] = item

        ordered = sorted(
            results.values(),
            key=lambda item: item["score"] if item["score"] is not None else -1.0,
            reverse=True,
        )
        return ordered[:limit]

    async def get(self, memory_id: str) -> dict[str, Any] | None:
        records = await self.vector.retrieve([memory_id])
        if not records:
            return None
        return self._to_memory(str(records[0].id), records[0].payload or {})

    async def list(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        scope = self._scope(user_id, agent_id, run_id)
        records = await self.vector.scroll(scope, limit=limit)
        items = [self._to_memory(str(r.id), r.payload or {}) for r in records]
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return items

    async def update(self, memory_id: str, text: str) -> dict[str, Any] | None:
        records = await self.vector.retrieve([memory_id])
        if not records:
            return None
        payload = records[0].payload or {}
        scope = {
            "user_id": payload.get("user_id"),
            "agent_id": payload.get("agent_id"),
            "run_id": payload.get("run_id"),
        }
        await self._write(
            memory_id,
            text,
            scope,
            payload.get("metadata") or {},
            created_at=payload.get("created_at"),
        )
        return await self.get(memory_id)

    async def delete(self, memory_id: str) -> bool:
        records = await self.vector.retrieve([memory_id])
        if not records:
            return False
        await self.vector.delete([memory_id])
        if self.graph:
            await self.graph.delete_memory(memory_id)
        return True

    async def delete_scope(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ) -> int:
        scope = self._scope(user_id, agent_id, run_id)
        if not any(scope.values()):
            raise ValueError("at least one of user_id/agent_id/run_id is required")
        deleted = await self.vector.delete_scope(scope)
        if self.graph and user_id:
            await self.graph.delete_scope(user_id, agent_id, run_id)
        return deleted

    # ------------------------------------------------------------ llm steps
    async def _extract_facts(self, convo: list[dict[str, str]]) -> list[str]:
        conversation = "\n".join(
            f"{turn.get('role', 'user')}: {turn.get('content', '')}" for turn in convo
        ).strip()
        if not conversation:
            return []
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": prompts.FACT_EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompts.fact_extraction_user(conversation)},
                ]
            )
        except LLMError as exc:
            logger.warning("fact extraction failed: %s", exc)
            return []
        facts = data.get("facts", []) if isinstance(data, dict) else data
        if not isinstance(facts, list):
            return []
        return [str(fact).strip() for fact in facts if str(fact).strip()]

    async def _decide(self, fact: str, existing: list[dict[str, str]]) -> dict[str, Any]:
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": prompts.UPDATE_DECISION_SYSTEM},
                    {"role": "user", "content": prompts.update_decision_user(fact, existing)},
                ]
            )
        except LLMError as exc:
            logger.warning("update decision failed, defaulting to ADD: %s", exc)
            return {"event": "ADD"}
        return data if isinstance(data, dict) else {"event": "ADD"}

    async def _extract_graph(self, text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": prompts.GRAPH_EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompts.graph_extraction_user(text)},
                ]
            )
        except LLMError as exc:
            logger.warning("graph extraction failed: %s", exc)
            return [], []
        if not isinstance(data, dict):
            return [], []
        entities = [
            {"name": str(e["name"]).strip(), "type": str(e.get("type", "concept")).strip()}
            for e in data.get("entities", [])
            if isinstance(e, dict) and e.get("name")
        ]
        relations = [
            {
                "source": str(r["source"]).strip(),
                "relation": str(r.get("relation", "related_to")).strip(),
                "target": str(r["target"]).strip(),
            }
            for r in data.get("relations", [])
            if isinstance(r, dict) and r.get("source") and r.get("target")
        ]
        return entities, relations

    async def _extract_entity_names(self, text: str) -> list[str]:
        try:
            data = await self.llm.chat_json(
                [
                    {"role": "system", "content": prompts.ENTITY_EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompts.entity_extraction_user(text)},
                ]
            )
        except LLMError as exc:
            logger.warning("entity extraction failed: %s", exc)
            return []
        names = data.get("entities", []) if isinstance(data, dict) else []
        return [str(name).strip() for name in names if str(name).strip()]

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _normalize(messages: list[dict[str, str]] | str) -> list[dict[str, str]]:
        if isinstance(messages, str):
            return [{"role": "user", "content": messages}]
        if isinstance(messages, dict):
            return [messages]
        return [
            {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
            for m in messages
            if isinstance(m, dict)
        ]

    @staticmethod
    def _scope(
        user_id: str | None, agent_id: str | None, run_id: str | None
    ) -> dict[str, str | None]:
        return {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}

    @staticmethod
    def _in_scope(payload: dict[str, Any], scope: dict[str, str | None]) -> bool:
        return all(
            payload.get(key) == value
            for key, value in scope.items()
            if value is not None
        )

    @staticmethod
    def _to_memory(memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": memory_id,
            "memory": payload.get("memory", ""),
            "user_id": payload.get("user_id"),
            "agent_id": payload.get("agent_id"),
            "run_id": payload.get("run_id"),
            "metadata": payload.get("metadata") or {},
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "score": None,
            "source": None,
        }
