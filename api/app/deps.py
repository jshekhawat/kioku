"""Shared singletons wiring configuration to clients and stores."""

from __future__ import annotations

import logging

from app.clients.embeddings import EmbeddingClient
from app.clients.llm import LLMClient
from app.config import get_settings
from app.memory.service import MemoryService
from app.stores.graph import GraphStore
from app.stores.vector import VectorStore

logger = logging.getLogger(__name__)

settings = get_settings()

llm = LLMClient(
    settings.llm_endpoint(),
    model=settings.llm_model,
    temperature=settings.llm_temperature,
    max_tokens=settings.llm_max_tokens,
)

embeddings = EmbeddingClient(
    settings.embed_endpoint(),
    model=settings.embed_model,
    dim=settings.embed_dim,
    batch_size=settings.embed_batch_size,
)

vector = VectorStore(
    url=settings.qdrant_url,
    collection=settings.qdrant_collection,
    dim=settings.embed_dim,
    api_key=settings.qdrant_api_key,
)

graph: GraphStore | None = (
    GraphStore(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        graph_name=settings.falkordb_graph,
    )
    if settings.graph_enabled
    else None
)

service = MemoryService(
    llm=llm,
    embeddings=embeddings,
    vector=vector,
    graph=graph,
    similarity_threshold=settings.similarity_threshold,
    default_limit=settings.default_search_limit,
)


async def startup() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    await vector.ensure_collection()
    if graph is not None:
        try:
            await graph.verify_connection()
            logger.info("connected to falkordb graph %s", settings.falkordb_graph)
        except Exception as exc:  # graph is optional at runtime
            logger.warning("falkordb unavailable, graph features disabled: %s", exc)


async def shutdown() -> None:
    await llm.aclose()
    await embeddings.aclose()
    await vector.aclose()
