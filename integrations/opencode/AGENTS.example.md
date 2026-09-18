# Global agent rules

## Long-term memory (kioku)

A kioku MCP server exposes persistent memory tools: `kioku_add_memory`,
`kioku_search_memory`, `kioku_list_memories`, `kioku_update_memory`,
`kioku_delete_memory`. Relevant memories are also injected automatically at the
start of each turn by the `kioku` plugin.

### Capture

- When the user states a durable preference, identity fact, goal, relationship,
  or project decision, save it with `kioku_add_memory` (default `user_id`).
  Write one concise third-person statement per call, e.g.
  "User prefers pnpm over npm".
- If the user says "remember ...", always save it.
- Never save transient details, secrets, credentials, API keys, or anything
  already captured in the repository or these rules.
- If a stored fact turns out to be wrong or outdated, find it with
  `kioku_search_memory`, then correct or remove it with `kioku_update_memory`
  or `kioku_delete_memory`.

### Recall

- Automatic recall is approximate and may miss things. If prior context about
  the user would change your answer, call `kioku_search_memory` before
  responding.
