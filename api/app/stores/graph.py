"""FalkorDB-backed knowledge graph for entities and relations.

FalkorDB speaks a subset of openCypher over the Redis protocol, which keeps the
graph container small and fast for local use. The synchronous client is wrapped
with ``asyncio.to_thread`` so it plays nicely with the async API.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from falkordb import FalkorDB

logger = logging.getLogger(__name__)


class GraphStore:
    def __init__(self, host: str, port: int, graph_name: str) -> None:
        self._host = host
        self._port = port
        self._db: FalkorDB | None = None
        self.graph_name = graph_name

    def _connection(self) -> FalkorDB:
        if self._db is None:
            self._db = FalkorDB(host=self._host, port=self._port)
        return self._db

    @property
    def graph(self):
        return self._connection().select_graph(self.graph_name)

    async def verify_connection(self) -> None:
        await asyncio.to_thread(lambda: self.graph.query("RETURN 1"))

    async def upsert_memory(
        self,
        memory: dict[str, Any],
        entities: list[dict[str, str]],
        relations: list[dict[str, str]],
    ) -> None:
        def _run() -> None:
            graph = self.graph
            graph.query(
                """
                MERGE (m:Memory {id: $id})
                SET m.text = $text,
                    m.user_id = $user_id,
                    m.agent_id = $agent_id,
                    m.run_id = $run_id,
                    m.created_at = $created_at,
                    m.updated_at = $updated_at
                """,
                {
                    "id": memory["id"],
                    "text": memory["memory"],
                    "user_id": memory.get("user_id"),
                    "agent_id": memory.get("agent_id"),
                    "run_id": memory.get("run_id"),
                    "created_at": memory.get("created_at"),
                    "updated_at": memory.get("updated_at"),
                },
            )

            if entities:
                graph.query(
                    """
                    MATCH (m:Memory {id: $id})
                    UNWIND $entities AS e
                    MERGE (n:Entity {name: e.name, user_id: $user_id})
                    ON CREATE SET n.type = e.type
                    MERGE (m)-[:MENTIONS]->(n)
                    """,
                    {"id": memory["id"], "user_id": memory.get("user_id"), "entities": entities},
                )

            if relations:
                graph.query(
                    """
                    UNWIND $relations AS r
                    MERGE (a:Entity {name: r.source, user_id: $user_id})
                    MERGE (b:Entity {name: r.target, user_id: $user_id})
                    MERGE (a)-[:RELATES {type: r.relation}]->(b)
                    """,
                    {"user_id": memory.get("user_id"), "relations": relations},
                )

        await asyncio.to_thread(_run)

    async def related_memory_ids(
        self,
        entity_names: list[str],
        user_id: str,
        limit: int = 20,
    ) -> list[str]:
        if not entity_names or not user_id:
            return []
        names = [name.lower() for name in entity_names]

        def _run() -> list[str]:
            graph = self.graph
            direct = graph.query(
                """
                MATCH (n:Entity)-[:MENTIONS]-(m:Memory)
                WHERE n.user_id = $user_id AND toLower(n.name) IN $names
                RETURN DISTINCT m.id AS id
                LIMIT $limit
                """,
                {"user_id": user_id, "names": names, "limit": limit},
            )
            hop = graph.query(
                """
                MATCH (n:Entity {user_id: $user_id})-[:RELATES]-(:Entity)-[:MENTIONS]-(m:Memory)
                WHERE toLower(n.name) IN $names
                RETURN DISTINCT m.id AS id
                LIMIT $limit
                """,
                {"user_id": user_id, "names": names, "limit": limit},
            )
            ids: list[str] = []
            for result in (direct, hop):
                for row in result.result_set:
                    if row and row[0] not in ids:
                        ids.append(row[0])
            return ids

        return await asyncio.to_thread(_run)

    async def delete_memory(self, memory_id: str) -> None:
        await asyncio.to_thread(
            lambda: self.graph.query(
                "MATCH (m:Memory {id: $id}) DETACH DELETE m", {"id": memory_id}
            )
        )

    async def delete_scope(self, user_id: str, agent_id: str | None = None,
                           run_id: str | None = None) -> None:
        clauses = ["m.user_id = $user_id"]
        params: dict[str, Any] = {"user_id": user_id}
        if agent_id:
            clauses.append("m.agent_id = $agent_id")
            params["agent_id"] = agent_id
        if run_id:
            clauses.append("m.run_id = $run_id")
            params["run_id"] = run_id
        where = " AND ".join(clauses)

        await asyncio.to_thread(
            lambda: self.graph.query(f"MATCH (m:Memory) WHERE {where} DETACH DELETE m", params)
        )
