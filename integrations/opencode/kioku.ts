const BASE_URL = process.env.KIOKU_BASE_URL ?? "http://localhost:8000"
const USER_ID = process.env.KIOKU_USER_ID ?? "default"
const LIMIT = Number(process.env.KIOKU_RECALL_LIMIT ?? "5")
const THRESHOLD = process.env.KIOKU_RECALL_THRESHOLD
const TTL_MS = Number(process.env.KIOKU_RECALL_TTL_MS ?? "120000")
const MAX_CACHE = 256

type Pending = { text: string; ts: number }

const pending = new Map<string, Pending>()
const resultCache = new Map<string, string | null>()

// Minimal local shapes for the V2 plugin API surface this plugin uses. Avoids a
// runtime dependency on `@opencode/plugin`, which OpenCode does not bundle for
// local server plugins. See https://opencode.ai/v2/docs/build/plugins.
type SystemPart = { type: "text"; text: string }

interface PromptHookEvent {
  readonly sessionID: string
  prompt: { text: string }
}

interface ContextHookEvent {
  readonly sessionID: string
  system: SystemPart[]
}

interface SessionHookContext {
  hook(
    name: "prompt",
    callback: (event: PromptHookEvent) => void | Promise<void>,
  ): Promise<unknown>
  hook(
    name: "context",
    callback: (event: ContextHookEvent) => void | Promise<void>,
  ): Promise<unknown>
}

interface PluginContext {
  session: SessionHookContext
}

async function recall(query: string): Promise<string | null> {
  if (resultCache.has(query)) return resultCache.get(query) ?? null

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 3000)
  try {
    const body: Record<string, unknown> = {
      query,
      user_id: USER_ID,
      limit: LIMIT,
      use_graph: false,
    }
    if (THRESHOLD) body.threshold = Number(THRESHOLD)

    const res = await fetch(`${BASE_URL}/v1/memories/search`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!res.ok) return null

    const data = (await res.json()) as { results?: Array<{ memory?: string }> }
    const memories = (data.results ?? [])
      .map((r) => r.memory?.trim())
      .filter((m): m is string => Boolean(m))

    const block = memories.length
      ? "## Relevant long-term memories about the user\n" +
        memories.map((m) => `- ${m}`).join("\n")
      : null

    resultCache.set(query, block)
    if (resultCache.size > MAX_CACHE) {
      const oldest = resultCache.keys().next().value
      if (oldest !== undefined) resultCache.delete(oldest)
    }
    return block
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

export default {
  id: "kioku",
  async setup(ctx: PluginContext) {
    // `chat.message` in V1. Capture the submitted prompt so the request hook
    // below can recall memories for it.
    await ctx.session.hook("prompt", (event) => {
      const text = event.prompt.text.trim()
      if (!text || text.startsWith("/")) return
      pending.set(event.sessionID, { text, ts: Date.now() })
    })

    // `experimental.chat.system.transform` in V1. Runs immediately before each
    // model request; append recalled memories to the system instructions.
    await ctx.session.hook("context", async (event) => {
      const entry = pending.get(event.sessionID)
      if (!entry) return
      if (Date.now() - entry.ts > TTL_MS) {
        pending.delete(event.sessionID)
        return
      }
      const block = await recall(entry.text)
      if (block) event.system.push({ type: "text", text: block })
    })

    return () => {
      pending.clear()
      resultCache.clear()
    }
  },
}
