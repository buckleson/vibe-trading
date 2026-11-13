import { fetchCSRFToken } from './client'

export interface ClaudeCliStatus {
  installed: boolean
  path: string | null
  version: string | null
  logged_in: boolean
  auth_method: string | null
}

export interface ClaudeExternalStatus {
  connected: boolean
  last_seen: string | null
  last_tool: string | null
  calls: number
  client: string | null
}

export interface ClaudeSkill {
  name: string
  description: string
  scope: 'desk' | 'user'
}

export interface ClaudeStatus {
  status: string
  cli: ClaudeCliStatus
  in_app: { ready: boolean; running: string[] }
  external: ClaudeExternalStatus
  connected: boolean
  sandbox: boolean
  market_data: { source: 'live' | 'simulated'; provider?: string; message?: string } | null
  desk_dir: string
  skills: ClaudeSkill[]
  access_levels: Record<string, { label: string; description: string }>
}

export interface ClaudeConnectInfo {
  status: string
  server_name: string
  command: string
  mcp_json: Record<string, unknown>
  desk_dir: string
  host: string
}

export interface ClaudeConversationSummary {
  id: string
  title: string
  updated: string
  created: string
  turns: number
}

export interface StoredItem {
  role: 'user' | 'assistant' | 'tool' | 'meta'
  text?: string
  name?: string
  input?: unknown
  result?: string
  is_error?: boolean
  cost_usd?: number
  duration_ms?: number
  turns?: number
  at?: string
}

export interface ClaudeConversation {
  id: string
  title: string
  session_id?: string
  items: StoredItem[]
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { credentials: 'include', headers: { Accept: 'application/json' } })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.message || 'Request failed')
  return data as T
}

async function send<T>(url: string, method: string, body?: unknown): Promise<T> {
  const csrf = await fetchCSRFToken()
  const res = await fetch(url, {
    method,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.message || 'Request failed')
  return data as T
}

export const claudeApi = {
  status: (refresh = false) => getJson<ClaudeStatus>(`/claude/api/status${refresh ? '?refresh=1' : ''}`),
  connect: () => getJson<ClaudeConnectInfo>('/claude/api/connect'),
  conversations: () =>
    getJson<{ conversations: ClaudeConversationSummary[] }>('/claude/api/conversations').then(
      (d) => d.conversations
    ),
  conversation: (id: string) =>
    getJson<{ conversation: ClaudeConversation }>(`/claude/api/conversations/${id}`).then(
      (d) => d.conversation
    ),
  deleteConversation: (id: string) => send(`/claude/api/conversations/${id}`, 'DELETE'),
  stop: (id: string) => send(`/claude/api/chat/${id}/stop`, 'POST'),

  /** Stream one turn. Calls onEvent for every server-sent event, resolves at the end. */
  async chat(
    payload: { message: string; conversation_id?: string | null; access?: string; model?: string },
    onEvent: (event: Record<string, unknown>) => void,
    signal?: AbortSignal
  ): Promise<void> {
    const csrf = await fetchCSRFToken()
    const res = await fetch('/claude/api/chat', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'text/event-stream' },
      body: JSON.stringify(payload),
      signal,
    })
    if (!res.ok || !res.body) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data?.message || 'Claude could not start.')
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx = buffer.indexOf('\n\n')
      while (idx !== -1) {
        const chunk = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        for (const line of chunk.split('\n')) {
          if (line.startsWith('data: ')) {
            try {
              onEvent(JSON.parse(line.slice(6)))
            } catch {
              // a partial or non-JSON line; skip it
            }
          }
        }
        idx = buffer.indexOf('\n\n')
      }
    }
  },
}
