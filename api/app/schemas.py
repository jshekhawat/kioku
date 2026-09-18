"""Pydantic request/response schemas for the REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str


class AddRequest(BaseModel):
    messages: list[Message] | str = Field(
        ...,
        description="Conversation turns or a single raw string to remember.",
    )
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    infer: bool = Field(
        True,
        description="When true, run LLM fact extraction/dedup. When false, store verbatim.",
    )


class MemoryResult(BaseModel):
    id: str
    memory: str
    event: Literal["ADD", "UPDATE", "DELETE", "NONE"]
    previous: str | None = None


class AddResponse(BaseModel):
    results: list[MemoryResult]


class SearchRequest(BaseModel):
    query: str
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    limit: int | None = None
    threshold: float | None = None
    use_graph: bool | None = Field(
        None, description="Override graph expansion for this query."
    )


class MemoryOut(BaseModel):
    id: str
    memory: str
    user_id: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    score: float | None = None
    source: Literal["vector", "graph", "both"] | None = None


class SearchResponse(BaseModel):
    results: list[MemoryOut]


class ListResponse(BaseModel):
    results: list[MemoryOut]


class UpdateRequest(BaseModel):
    memory: str


class DeleteResponse(BaseModel):
    deleted: int
