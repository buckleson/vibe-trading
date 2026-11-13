import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { type ClaudeStatus, claudeApi, type StoredItem } from '@/api/claude'

export interface ChatItem {
  id: string
  role: 'user' | 'assistant' | 'tool' | 'meta' | 'error' | 'info'
  text?: string
  name?: string
  input?: unknown
  result?: string
  isError?: boolean
  pending?: boolean
  costUsd?: number
  durationMs?: number
  turns?: number
}

interface ClaudeStore {
  panelOpen: boolean
  conversationId: string | null
  items: ChatItem[]
  streaming: boolean
  access: 'trade' | 'full'
  status: ClaudeStatus | null
  mcpState: string | null
  historyVersion: number

  setPanelOpen: (open: boolean) => void
  togglePanel: () => void
  setAccess: (access: 'trade' | 'full') => void
  refreshStatus: (force?: boolean) => Promise<void>
  newConversation: () => void
  openConversation: (id: string) => Promise<void>
  send: (message: string) => Promise<void>
  stop: () => Promise<void>
}

let seq = 0
const nid = () => `i${Date.now().toString(36)}${(seq++).toString(36)}`
let controller: AbortController | null = null

function fromStored(items: StoredItem[]): ChatItem[] {
  return items.map((it) => ({
    id: nid(),
    role: it.role,
    text: it.text,
    name: it.name,
    input: it.input,
    result: it.result,
    isError: it.is_error,
    costUsd: it.cost_usd,
    durationMs: it.duration_ms,
    turns: it.turns,
  }))
}

export const useClaudeStore = create<ClaudeStore>()(
  persist(
    (set, get) => ({
      panelOpen: false,
      conversationId: null,
      items: [],
      streaming: false,
      access: 'trade',
      status: null,
      mcpState: null,
      historyVersion: 0,

      setPanelOpen: (open) => set({ panelOpen: open }),
      togglePanel: () => set({ panelOpen: !get().panelOpen }),
      setAccess: (access) => set({ access }),

      refreshStatus: async (force = false) => {
        try {
          set({ status: await claudeApi.status(force) })
        } catch {
          // keep the last known status
        }
      },

      newConversation: () => {
        if (get().streaming) return
        set({ conversationId: null, items: [], mcpState: null })
      },

      openConversation: async (id) => {
        if (get().streaming) return
        try {
          const conv = await claudeApi.conversation(id)
          set({ conversationId: id, items: fromStored(conv.items), mcpState: null })
        } catch {
          set({ conversationId: null, items: [] })
        }
      },

      stop: async () => {
        const id = get().conversationId
        if (id) {
          try {
            await claudeApi.stop(id)
          } catch {
            // the stream ending is what matters
          }
        }
        controller?.abort()
      },

      send: async (message) => {
        const text = message.trim()
        if (!text || get().streaming) return
        set((s) => ({
          streaming: true,
          items: [...s.items, { id: nid(), role: 'user', text }],
        }))

        // The assistant item text deltas are appended to, and tool items by id.
        let currentAssistant: string | null = null
        const toolIds = new Map<string, string>()

        const patch = (id: string, fn: (it: ChatItem) => ChatItem) =>
          set((s) => ({ items: s.items.map((it) => (it.id === id ? fn(it) : it)) }))
        const push = (item: ChatItem) => set((s) => ({ items: [...s.items, item] }))

        const ensureAssistant = () => {
          if (!currentAssistant) {
            currentAssistant = nid()
            push({ id: currentAssistant, role: 'assistant', text: '', pending: true })
          }
          return currentAssistant
        }

        const onEvent = (ev: Record<string, unknown>) => {
          const type = ev.type as string
          if (type === 'bridge') {
            const event = ev.event as string
            if (event === 'started' && ev.conversation_id) {
              set({ conversationId: ev.conversation_id as string })
            } else if (event === 'error' || event === 'timeout') {
              push({
                id: nid(),
                role: 'error',
                text: (ev.text as string) || 'The answer took too long and was stopped.',
              })
            } else if (event === 'log' && ev.text) {
              const line = String(ev.text)
              if (/error|denied|not logged|login/i.test(line)) {
                push({ id: nid(), role: 'error', text: line })
              }
            }
            return
          }
          if (type === 'system' && ev.subtype === 'init') {
            const servers = (ev.mcp_servers as { name: string; status: string }[]) || []
            const bk = servers.find((sv) => sv.name === 'buckleson')
            set({ mcpState: bk ? bk.status : 'not configured' })
            return
          }
          if (type === 'stream_event') {
            const e = ev.event as Record<string, unknown>
            if (e?.type === 'content_block_start') {
              const block = e.content_block as Record<string, unknown>
              if (block?.type === 'text') {
                currentAssistant = null
                ensureAssistant()
              }
            } else if (e?.type === 'content_block_delta') {
              const delta = e.delta as Record<string, unknown>
              if (delta?.type === 'text_delta' && typeof delta.text === 'string') {
                const id = ensureAssistant()
                const t = delta.text
                patch(id, (it) => ({ ...it, text: (it.text || '') + t }))
              }
            }
            return
          }
          if (type === 'assistant') {
            const msg = ev.message as { content?: Record<string, unknown>[] }
            for (const block of msg?.content || []) {
              if (block.type === 'text' && typeof block.text === 'string') {
                const id = ensureAssistant()
                const finalText = block.text
                patch(id, (it) => ({ ...it, text: finalText, pending: false }))
              } else if (block.type === 'tool_use') {
                if (currentAssistant) patch(currentAssistant, (it) => ({ ...it, pending: false }))
                currentAssistant = null
                const id = nid()
                toolIds.set(block.id as string, id)
                push({ id, role: 'tool', name: block.name as string, input: block.input, pending: true })
              }
            }
            return
          }
          if (type === 'user') {
            const msg = ev.message as { content?: Record<string, unknown>[] | string }
            const content = Array.isArray(msg?.content) ? msg.content : []
            for (const block of content) {
              if (block.type === 'tool_result') {
                const id = toolIds.get(block.tool_use_id as string)
                if (!id) continue
                let result = block.content as unknown
                if (Array.isArray(result)) {
                  result = result
                    .map((c: Record<string, unknown>) => (typeof c.text === 'string' ? c.text : ''))
                    .join('\n')
                }
                patch(id, (it) => ({
                  ...it,
                  pending: false,
                  result: String(result ?? '').slice(0, 6000),
                  isError: Boolean(block.is_error),
                }))
              }
            }
            return
          }
          if (type === 'result') {
            if (currentAssistant) patch(currentAssistant, (it) => ({ ...it, pending: false }))
            const hasAnswer = get().items.some((it) => it.role === 'assistant' && it.text)
            if (!hasAnswer && typeof ev.result === 'string' && ev.result) {
              push({ id: nid(), role: 'assistant', text: ev.result as string })
            }
            if (ev.is_error && typeof ev.result === 'string') {
              push({ id: nid(), role: 'error', text: ev.result as string })
            }
            push({
              id: nid(),
              role: 'meta',
              costUsd: ev.total_cost_usd as number,
              durationMs: ev.duration_ms as number,
              turns: ev.num_turns as number,
            })
          }
        }

        controller = new AbortController()
        try {
          await claudeApi.chat(
            {
              message: text,
              conversation_id: get().conversationId,
              access: get().access,
            },
            onEvent,
            controller.signal
          )
        } catch (err) {
          if ((err as Error).name !== 'AbortError') {
            push({ id: nid(), role: 'error', text: (err as Error).message })
          } else {
            push({ id: nid(), role: 'info', text: 'Stopped.' })
          }
        } finally {
          controller = null
          set((s) => ({
            streaming: false,
            historyVersion: s.historyVersion + 1,
            items: s.items.map((it) => (it.pending ? { ...it, pending: false } : it)),
          }))
        }
      },
    }),
    {
      name: 'buckleson-claude',
      partialize: (s) => ({ panelOpen: s.panelOpen, conversationId: s.conversationId, access: s.access }),
    }
  )
)
