import type { Plugin } from "@opencode-ai/plugin"

const BASE_URL = process.env.KIOKU_BASE_URL ?? "http://localhost:8000"
const USER_ID = process.env.KIOKU_USER_ID ?? "default"
const LIMIT = Number(process.env.KIOKU_RECALL_LIMIT ?? "5")
const THRESHOLD = process.env.KIOKU_RECALL_THRESHOLD
const TTL_MS = Number(process.env.KIOKU_RECALL_TTL_MS ?? "120000")
const MAX_CACHE = 256

type Pending = { text: string; ts: number }

const pending = new Map<string, Pending>()
const resultCache = new Map<string, string | null>()

function extractText(parts: unknown[]): string {
  return parts
    .filter(
      (p): p is { type: string; text: string } =>
        typeof p === "object" &&
        p !== null &&
        (p as { type?: string }).type === "text" &&
        typeof (p as { text?: unknown }).text === "string",
    )
    .map((p) => p.text)
    .join("\n")
    .trim()
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

export const KiokuPlugin: Plugin = async () => {
  return {
    "chat.message": async (input, output) => {
      const text = extractText(output.parts ?? [])
      if (!text || text.startsWith("/")) return
      pending.set(input.sessionID, { text, ts: Date.now() })
    },

    "experimental.chat.system.transform": async (input, output) => {
      if (!input.sessionID) return
      const entry = pending.get(input.sessionID)
      if (!entry) return
      if (Date.now() - entry.ts > TTL_MS) {
        pending.delete(input.sessionID)
        return
      }
      const block = await recall(entry.text)
      if (block) output.system.push(block)
    },
  }
}
