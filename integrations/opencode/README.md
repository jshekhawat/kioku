# OpenCode integration

Two optional pieces on top of the MCP server config:

- `kioku.ts` — an OpenCode plugin for **automatic recall**. Before each turn it
  searches kioku and injects the top matches into the system prompt, so the model
  doesn't have to remember to call the search tool. Recall is vector-only
  (`use_graph: false`) to avoid an extra LLM call per turn. Failures are silent so
  chat is never blocked.
- `AGENTS.example.md` — a **capture policy** telling the agent when to save,
  update, or delete memories via the `kioku_*` MCP tools.

## Install

Make sure the MCP server is configured first (see the main README) and that the
`api` (`:8000`) and `mcp` (`:8090`) containers are running.

Global (all projects):

```bash
mkdir -p ~/.config/opencode/plugins
cp kioku.ts ~/.config/opencode/plugins/kioku.ts
cat AGENTS.example.md >> ~/.config/opencode/AGENTS.md
```

Project-scoped (one repo):

```bash
mkdir -p .opencode/plugins
cp kioku.ts .opencode/plugins/kioku.ts
cat AGENTS.example.md >> AGENTS.md
```

Restart OpenCode afterwards — config and plugins are loaded once at startup.

## Configuration

Set these environment variables in the environment OpenCode runs in (not in
`.env`, which the plugin does not read):

| Variable | Default | Purpose |
| --- | --- | --- |
| `KIOKU_BASE_URL` | `http://localhost:8000` | kioku REST API base URL |
| `KIOKU_USER_ID` | `default` | Scope for recall |
| `KIOKU_RECALL_LIMIT` | `5` | Max memories injected per turn |
| `KIOKU_RECALL_THRESHOLD` | server default | Minimum similarity score |
| `KIOKU_RECALL_TTL_MS` | `120000` | How long a turn's query is reused |

## Notes

- No build step: OpenCode loads the TypeScript plugin directly.
- The plugin resolves `@opencode-ai/plugin` from your OpenCode config directory's
  `node_modules`; the import is type-only and is stripped at runtime.
- The capture policy is a suggestion the model follows. Capture is intentionally
  left out of the plugin because `add_memory` with `infer: true` triggers its own
  LLM extraction call, which would add latency and cost on every turn.
