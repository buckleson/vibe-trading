import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/claude', () => ({
  claudeApi: {
    chat: vi.fn(),
    stop: vi.fn(),
    status: vi.fn(),
    conversation: vi.fn(),
  },
}))

import { claudeApi } from '@/api/claude'
import { useClaudeStore } from './claudeStore'

const chat = claudeApi.chat as unknown as ReturnType<typeof vi.fn>

describe('claudeStore stream handling', () => {
  beforeEach(() => {
    useClaudeStore.setState({ items: [], conversationId: null, streaming: false, mcpState: null })
    chat.mockReset()
  })

  it('builds user, streamed answer, tool and meta items from the CLI events', async () => {
    chat.mockImplementation(async (_payload: unknown, onEvent: (e: Record<string, unknown>) => void) => {
      onEvent({ type: 'bridge', event: 'started', conversation_id: 'c-1' })
      onEvent({ type: 'system', subtype: 'init', mcp_servers: [{ name: 'buckleson', status: 'connected' }] })
      onEvent({ type: 'stream_event', event: { type: 'content_block_start', content_block: { type: 'text' } } })
      onEvent({ type: 'stream_event', event: { type: 'content_block_delta', delta: { type: 'text_delta', text: 'Placing ' } } })
      onEvent({ type: 'stream_event', event: { type: 'content_block_delta', delta: { type: 'text_delta', text: 'it.' } } })
      onEvent({ type: 'assistant', message: { content: [{ type: 'text', text: 'Placing it.' }] } })
      onEvent({
        type: 'assistant',
        message: { content: [{ type: 'tool_use', id: 't1', name: 'mcp__buckleson__place_order', input: { symbol: 'INFY' } }] },
      })
      onEvent({
        type: 'user',
        message: { content: [{ type: 'tool_result', tool_use_id: 't1', content: [{ type: 'text', text: 'orderid 42' }] }] },
      })
      onEvent({ type: 'result', total_cost_usd: 0.01, duration_ms: 1200, num_turns: 2 })
    })

    await useClaudeStore.getState().send('buy 5 infy')
    const s = useClaudeStore.getState()

    expect(s.conversationId).toBe('c-1')
    expect(s.mcpState).toBe('connected')
    expect(s.streaming).toBe(false)
    expect(s.items.map((i) => i.role)).toEqual(['user', 'assistant', 'tool', 'meta'])
    expect(s.items[1].text).toBe('Placing it.')
    expect(s.items[2]).toMatchObject({ name: 'mcp__buckleson__place_order', result: 'orderid 42', pending: false })
    expect(s.items[3]).toMatchObject({ costUsd: 0.01, durationMs: 1200, turns: 2 })
  })

  it('shows a readable error when Claude cannot start', async () => {
    chat.mockRejectedValue(new Error('Claude Code is not installed on this machine.'))
    await useClaudeStore.getState().send('hello')
    const items = useClaudeStore.getState().items
    expect(items.at(-1)).toMatchObject({ role: 'error', text: 'Claude Code is not installed on this machine.' })
    expect(useClaudeStore.getState().streaming).toBe(false)
  })

  it('ignores an empty message', async () => {
    await useClaudeStore.getState().send('   ')
    expect(chat).not.toHaveBeenCalled()
    expect(useClaudeStore.getState().items).toHaveLength(0)
  })
})
