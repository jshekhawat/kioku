# kioku

Locally hosted long-term memory for AI agents, in the spirit of mem0 / supermemory.
Runs entirely on your machine with Docker Compose: **OpenRouter** (or Ollama) for
reasoning, **Ollama** for embeddings, **Qdrant** for vectors, and **FalkorDB** for a
knowledge graph.

- REST API (`:8000`) for any app
- MCP server (`:8090/mcp`) for Claude Code, Cursor, and other MCP clients
- LLM fact extraction + consolidation (ADD / UPDATE / DELETE / NONE)
- Multi-tenant scoping by `user_id`, `agent_id`, `run_id`
- Knowledge graph of entities and relations, used to expand semantic search

## Architecture

```
                 +----------------+
  REST  :8000 -->|                |--> Qdrant      (vectors + payload)
                 |  kioku (api)   |
  MCP   :8090 -->|                |--> FalkorDB    (entities + relations)
                 +-------+--------+
                         |
             +-----------+-----------+
             |                       |
     OpenRouter (chat)        Ollama (embeddings)
```

## Quickstart

```bash
cp .env.example .env
# put your OpenRouter key in .env: KIOKU_OPENROUTER_API_KEY=sk-or-...
docker compose up -d --build
```

This starts Qdrant, FalkorDB, Ollama, pulls `nomic-embed-text`, then the API and
MCP server. Check it:

```bash
curl localhost:8000/v1/health
open http://localhost:8000/docs
```

### Using a local chat model instead of OpenRouter

Ollama is already in the stack. Point the LLM at it:

```env
KIOKU_LLM_PROVIDER=ollama
KIOKU_LLM_MODEL=llama3.2
```

and pull the model once:

```bash
docker compose exec ollama ollama pull llama3.2
```

### Using Ollama already running on your host

Set `KIOKU_OLLAMA_BASE_URL=http://host.docker.internal:11434` and remove/ignore the
bundled `ollama` service (`docker compose up -d --scale ollama=0 ...` or start only
the services you need). `host.docker.internal` is mapped on Linux via `extra_hosts`.

## API

Add memories (LLM extracts and dedups facts):

```bash
curl -X POST localhost:8000/v1/memories -H 'content-type: application/json' -d '{
  "messages": [
    {"role": "user", "content": "I moved to Berlin in June and I am allergic to peanuts."},
    {"role": "assistant", "content": "Noted!"}
  ],
  "user_id": "alice"
}'
```

Store verbatim without LLM extraction: set `"infer": false`.

Search:

```bash
curl -X POST localhost:8000/v1/memories/search -H 'content-type: application/json' -d '{
  "query": "What food should I avoid?",
  "user_id": "alice",
  "limit": 5
}'
```

Other endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/memories` | Add / infer memories |
| `POST` | `/v1/memories/search` | Semantic (+ graph) search |
| `GET` | `/v1/memories` | List by scope, newest first |
| `GET` | `/v1/memories/{id}` | Fetch one |
| `PATCH` | `/v1/memories/{id}` | Replace text |
| `DELETE` | `/v1/memories/{id}` | Delete one |
| `DELETE` | `/v1/memories` | Delete by scope (`user_id`/`agent_id`/`run_id`) |
| `GET` | `/v1/health` | Liveness |

## MCP

Streamable HTTP endpoint: `http://localhost:8090/mcp`.

Claude Code:

```bash
claude mcp add --transport http kioku http://localhost:8090/mcp
```

Generic client config:

```json
{
  "mcpServers": {
    "kioku": { "type": "http", "url": "http://localhost:8090/mcp" }
  }
}
```

Tools: `add_memory`, `search_memory`, `list_memories`, `update_memory`, `delete_memory`.

## Configuration

All settings use the `KIOKU_` prefix (see `.env.example`).

| Variable | Default | Notes |
| --- | --- | --- |
| `KIOKU_LLM_PROVIDER` | `openrouter` | `openrouter`, `ollama`, `openai` |
| `KIOKU_LLM_MODEL` | `openai/gpt-4o-mini` | Any OpenRouter/Ollama model id |
| `KIOKU_OPENROUTER_API_KEY` | – | Required for OpenRouter |
| `KIOKU_EMBED_PROVIDER` | `ollama` | `ollama`, `openai` |
| `KIOKU_EMBED_MODEL` | `nomic-embed-text` | Must match `KIOKU_EMBED_DIM` |
| `KIOKU_EMBED_DIM` | `768` | Vector size; recreate collection if changed |
| `KIOKU_GRAPH_ENABLED` | `true` | Set `false` to disable knowledge graph |
| `KIOKU_SIMILARITY_THRESHOLD` | `0.1` | Minimum vector score for candidates |
| `KIOKU_QDRANT_URL` | `http://qdrant:6333` | |
| `KIOKU_FALKORDB_HOST` | `falkordb` | |

Changing `KIOKU_EMBED_MODEL`/`KIOKU_EMBED_DIM` after data exists requires dropping
the Qdrant collection (`kioku_memories`), since vector dimensions are fixed.

## How the pipeline works

1. `add` sends the conversation to the LLM for **fact extraction**.
2. Each fact is hashed (exact dedup) then embedded and matched against the top-k
   most similar memories **within the same scope**.
3. The LLM chooses `ADD`, `UPDATE`, `DELETE`, or `NONE` against those candidates.
4. Writes go to Qdrant; entities/relations are extracted and written to FalkorDB.
5. `search` does vector search, then (when `user_id` is set) expands results via
   graph neighbors before ranking.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e 'api[dev]'
export KIOKU_QDRANT_URL=http://localhost:6333
# run the infra only:
docker compose up -d qdrant falkordb ollama
# run the API locally:
uvicorn app.main:app --reload --app-dir api
ruff check api/app
```
