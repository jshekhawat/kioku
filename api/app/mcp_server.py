"""MCP server exposing kioku memory tools over streamable HTTP.

Run with ``python -m app.mcp_server``. The MCP endpoint is served at ``/mcp``
and is compatible with Claude Code, Cursor and other MCP clients.
"""

from __future__ import annotations

import asyncio
import json
import logging

from mcp.server.fastmcp import FastMCP

from app import deps
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

mcp = FastMCP("kioku", host=settings.mcp_host, port=settings.mcp_port)


def _dump(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


@mcp.tool()
async def add_memory(
    text: str,
    user_id: str = "default",
    agent_id: str | None = None,
    run_id: str | None = None,
    infer: bool = True,
) -> str:
    """Remember information about a user.

    Args:
        text: The conversation turn or raw text to remember.
        user_id: Owner of the memory.
        agent_id: Optional agent scope.
        run_id: Optional session/run scope.
        infer: Extract and consolidate facts with the LLM (true) or store verbatim (false).
    """
    results = await deps.service.add(
        messages=text,
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        infer=infer,
    )
    return _dump(results)


@mcp.tool()
async def search_memory(
    query: str,
    user_id: str = "default",
    agent_id: str | None = None,
    run_id: str | None = None,
    limit: int = 10,
    use_graph: bool = True,
) -> str:
    """Search stored memories semantically, optionally expanding via the knowledge graph."""
    results = await deps.service.search(
        query=query,
        user_id=user_id,
        agent_id=agent_id,
        run_id=run_id,
        limit=limit,
        use_graph=use_graph,
    )
    return _dump(results)


@mcp.tool()
async def list_memories(
    user_id: str = "default",
    agent_id: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
) -> str:
    """List stored memories for a scope, newest first."""
    results = await deps.service.list(
        user_id=user_id, agent_id=agent_id, run_id=run_id, limit=limit
    )
    return _dump(results)


@mcp.tool()
async def update_memory(memory_id: str, text: str) -> str:
    """Replace the text of an existing memory by id."""
    result = await deps.service.update(memory_id, text)
    return _dump(result or {"error": "memory not found"})


@mcp.tool()
async def delete_memory(memory_id: str) -> str:
    """Delete a single memory by id."""
    deleted = await deps.service.delete(memory_id)
    return _dump({"deleted": deleted})


def main() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    asyncio.run(deps.startup())
    logger.info("kioku mcp ready on %s:%s/mcp", settings.mcp_host, settings.mcp_port)
    try:
        mcp.run(transport="streamable-http")
    finally:
        asyncio.run(deps.shutdown())


if __name__ == "__main__":
    main()
