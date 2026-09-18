"""REST routes for the memory service."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import deps
from app.schemas import (
    AddRequest,
    AddResponse,
    DeleteResponse,
    ListResponse,
    MemoryOut,
    SearchRequest,
    SearchResponse,
    UpdateRequest,
)

router = APIRouter(prefix="/v1", tags=["memories"])


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/memories", response_model=AddResponse)
async def add_memories(request: AddRequest) -> AddResponse:
    messages = (
        request.messages
        if isinstance(request.messages, str)
        else [message.model_dump() for message in request.messages]
    )
    results = await deps.service.add(
        messages=messages,
        user_id=request.user_id,
        agent_id=request.agent_id,
        run_id=request.run_id,
        metadata=request.metadata,
        infer=request.infer,
    )
    return AddResponse(results=results)


@router.post("/memories/search", response_model=SearchResponse)
async def search_memories(request: SearchRequest) -> SearchResponse:
    results = await deps.service.search(
        query=request.query,
        user_id=request.user_id,
        agent_id=request.agent_id,
        run_id=request.run_id,
        limit=request.limit,
        threshold=request.threshold,
        use_graph=request.use_graph,
    )
    return SearchResponse(results=[MemoryOut(**item) for item in results])


@router.get("/memories", response_model=ListResponse)
async def list_memories(
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> ListResponse:
    results = await deps.service.list(
        user_id=user_id, agent_id=agent_id, run_id=run_id, limit=limit
    )
    return ListResponse(results=[MemoryOut(**item) for item in results])


@router.delete("/memories", response_model=DeleteResponse)
async def delete_memories(
    user_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
) -> DeleteResponse:
    try:
        deleted = await deps.service.delete_scope(
            user_id=user_id, agent_id=agent_id, run_id=run_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeleteResponse(deleted=deleted)


@router.get("/memories/{memory_id}", response_model=MemoryOut)
async def get_memory(memory_id: str) -> MemoryOut:
    memory = await deps.service.get(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return MemoryOut(**memory)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def update_memory(memory_id: str, request: UpdateRequest) -> MemoryOut:
    memory = await deps.service.update(memory_id, request.memory)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return MemoryOut(**memory)


@router.delete("/memories/{memory_id}", response_model=DeleteResponse)
async def delete_memory(memory_id: str) -> DeleteResponse:
    deleted = await deps.service.delete(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="memory not found")
    return DeleteResponse(deleted=1)
