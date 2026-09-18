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

This starts Qdrant, FalkorDB, the API and the MCP server. It expects an **external
Ollama** for embeddings (see below). Check it:

```bash
curl localhost:8000/v1/health
open http://localhost:8000/docs
```

### Ollama

The `ollama` and `ollama-init` services are opt-in under the `bundled-ollama`
profile, so kioku defaults to an Ollama you already run. Pick one:

**1. Ollama on the host (default).** Host port `11434` is used via
`host.docker.internal`, which is mapped on Linux through `extra_hosts`:

```env
KIOKU_OLLAMA_BASE_URL=http://host.docker.internal:11434
```

**2. Ollama in another container on a different Docker network.** Use the
override file to attach the API/MCP containers to that network and address Ollama
by container name:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.external-ollama.yml \
KIOKU_OLLAMA_NETWORK=my-net \
KIOKU_OLLAMA_BASE_URL=http://my-ollama:11434 \
docker compose up -d
```

The external network must already exist. You can persist the flag by adding
`COMPOSE_FILE=docker-compose.yml:docker-compose.external-ollama.yml`,
`KIOKU_OLLAMA_NETWORK` and `KIOKU_OLLAMA_BASE_URL` to `.env`.

**3. Bundle Ollama with kioku.** Start the profile and point at the service name:

```bash
KIOKU_OLLAMA_BASE_URL=http://ollama:11434 \
docker compose --profile bundled-ollama up -d
```

`ollama-init` will pull `KIOKU_EMBED_MODEL` automatically; add
`--profile bundled-ollama` again for later commands (e.g. `docker compose
--profile bundled-ollama exec ollama ollama pull llama3.2`).

### Using a local chat model instead of OpenRouter

Point the LLM at any of the Ollama setups above:

```env
KIOKU_LLM_PROVIDER=ollama
KIOKU_LLM_MODEL=llama3.2
```

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

OpenCode — add to `~/.config/opencode/opencode.json` (or `opencode.jsonc`;
global, all projects) or `opencode.json` in a project root (scoped):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "kioku": {
      "type": "remote",
      "url": "http://localhost:8090/mcp",
      "enabled": true
    }
  }
}
```

Restart opencode afterwards (config is not hot-reloaded). Tools are exposed with
the server-name prefix, e.g. `kioku_add_memory`, `kioku_search_memory`. The
`mcp` container must be running for opencode to connect.

### Automatic recall

The repo ships an OpenCode plugin in [`integrations/opencode/`](integrations/opencode/).
It searches kioku before each turn and injects the top matches into the system
prompt, so the model doesn't have to remember to call the search tool. Install it
globally (or copy into `.opencode/plugins/` for a single project):

```bash
mkdir -p ~/.config/opencode/plugins
cp integrations/opencode/kioku.ts ~/.config/opencode/plugins/kioku.ts
cat integrations/opencode/AGENTS.example.md >> ~/.config/opencode/AGENTS.md
```

The second command adds a capture policy that tells the agent when to save
memories. Recall is vector-only (`use_graph: false`) to avoid an extra LLM call
per turn, and failures are silent so chat is never blocked. Configurable via
`KIOKU_BASE_URL` (default `http://localhost:8000`), `KIOKU_USER_ID`,
`KIOKU_RECALL_LIMIT` (default `5`), `KIOKU_RECALL_THRESHOLD` and
`KIOKU_RECALL_TTL_MS`. See [`integrations/opencode/README.md`](integrations/opencode/README.md)
for details.

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
| `KIOKU_OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | External/host Ollama by default |
| `KIOKU_OLLAMA_NETWORK` | `ollama` | External Docker network for the override file |
| `KIOKU_EMBED_PROVIDER` | `ollama` | `ollama`, `openai` |
| `KIOKU_EMBED_MODEL` | `nomic-embed-text` | Must match `KIOKU_EMBED_DIM` |
| `KIOKU_EMBED_DIM` | `768` | Vector size; recreate collection if changed |
| `KIOKU_GRAPH_ENABLED` | `true` | Set `false` to disable knowledge graph |
| `KIOKU_SIMILARITY_THRESHOLD` | `0.1` | Minimum vector score for candidates |
| `KIOKU_QDRANT_URL` | `http://qdrant:6333` | |
| `KIOKU_QDRANT_RECREATE_ON_DIM_MISMATCH` | `false` | Drop/rebuild collection if `KIOKU_EMBED_DIM` changed |
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
