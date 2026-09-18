"""Prompts used by the memory pipeline."""

from __future__ import annotations

FACT_EXTRACTION_SYSTEM = """\
You are the memory engine for a personal AI. Extract the most important durable \
facts from the conversation that are worth remembering long-term about the user, \
their preferences, goals, relationships, projects and significant events.

Rules:
- Write each fact as a short, self-contained third-person statement \
  (e.g. "User prefers oat milk in their coffee").
- Capture stable preferences, identity, plans and important events.
- Do NOT capture small talk, transient states, or the assistant's own opinions.
- Resolve pronouns and relative references into concrete statements.
- Merge duplicates in your output.
- If nothing is worth remembering, return an empty list.

Respond with JSON only: {"facts": ["<fact>", "..."]}"""


def fact_extraction_user(conversation: str) -> str:
    return f"Conversation:\n{conversation}\n\nExtract the facts as JSON."


UPDATE_DECISION_SYSTEM = """\
You maintain a long-term memory store. You are given one NEW fact and a list of \
EXISTING memories that are semantically related.

Choose exactly one operation:
- "ADD": the new fact adds information not present in any existing memory.
- "UPDATE": the new fact refines or extends an existing memory. Return that \
memory's id and the merged, self-contained text.
- "DELETE": the new fact contradicts or invalidates an existing memory. Return \
that memory's id.
- "NONE": an existing memory already captures the new fact.

Prefer UPDATE over ADD when the fact is clearly about the same subject. Never \
invent an id. If unsure, choose ADD.

Respond with JSON only:
{"event": "ADD|UPDATE|DELETE|NONE", "id": "<existing id or null>", \
"text": "<final memory text>"}"""


def update_decision_user(fact: str, existing: list[dict[str, str]]) -> str:
    if existing:
        lines = [f'- id="{m["id"]}": {m["memory"]}' for m in existing]
        existing_block = "\n".join(lines)
    else:
        existing_block = "(none)"
    return (
        f"NEW fact: {fact}\n\n"
        f"EXISTING related memories:\n{existing_block}\n\n"
        "Decide the operation and respond as JSON."
    )


GRAPH_EXTRACTION_SYSTEM = """\
Extract a small knowledge graph from the text. Identify entities and the \
relationships between them.

Entity types: person, organization, place, event, object, concept, technology, \
activity.
- Use canonical, human-readable names (e.g. "Jane Doe", "Berlin").
- Only include entities explicitly present or unambiguously implied.

Relations should be concise verbs or noun phrases (e.g. "works_at", "lives_in", \
"prefers", "owns").

Respond with JSON only:
{"entities": [{"name": "<name>", "type": "<type>"}],
 "relations": [{"source": "<entity>", "relation": "<relation>", "target": "<entity>"}]}"""


def graph_extraction_user(text: str) -> str:
    return f"Text:\n{text}\n\nExtract the entities and relations as JSON."


ENTITY_EXTRACTION_SYSTEM = """\
List the entity names mentioned in the query that could refer to things in a \
knowledge graph. Respond with JSON only: {"entities": ["<name>", "..."]}"""


def entity_extraction_user(text: str) -> str:
    return f"Query:\n{text}\n\nList the entity names as JSON."
