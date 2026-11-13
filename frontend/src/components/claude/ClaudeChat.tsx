import { ArrowUp, ChevronRight, CircleAlert, Square, Wrench } from 'lucide-react'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'
import { type ChatItem, useClaudeStore } from '@/stores/claudeStore'

const SUGGESTIONS = [
  'What is my sandbox balance and open P&L?',
  'Buy 10 RELIANCE at market, intraday',
  'Show the NIFTY option chain near the money',
  'Scan the news on Indian markets today',
]

export function toolLabel(name?: string): { server: string | null; tool: string } {
  if (!name) return { server: null, tool: 'tool' }
  const m = name.match(/^mcp__([^_]+(?:_[^_]+)*?)__(.+)$/)
  if (m) return { server: m[1], tool: m[2] }
  return { server: null, tool: name }
}

function summariseInput(input: unknown): string {
  if (!input || typeof input !== 'object') return ''
  const obj = input as Record<string, unknown>
  const keys = ['symbol', 'exchange', 'action', 'quantity', 'price_type', 'product', 'query', 'url', 'command', 'pattern']
  const parts = keys
    .filter((k) => obj[k] !== undefined && obj[k] !== '')
    .map((k) => String(obj[k]))
  if (parts.length) return parts.join(' · ').slice(0, 90)
  const first = Object.values(obj).find((v) => typeof v === 'string') as string | undefined
  return first ? first.slice(0, 90) : ''
}

function ToolRow({ item }: { item: ChatItem }) {
  const [open, setOpen] = useState(false)
  const { server, tool } = toolLabel(item.name)
  const summary = summariseInput(item.input)
  return (
    <div className="rounded-lg border bg-card/60 text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <ChevronRight
          className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')}
        />
        <Wrench className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="font-medium text-foreground">{tool}</span>
        {server && <span className="text-muted-foreground">{server}</span>}
        {summary && <span className="truncate text-muted-foreground">{summary}</span>}
        <span className="ml-auto shrink-0">
          {item.pending ? (
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand bk-pulse" />
          ) : item.isError ? (
            <span className="text-destructive">failed</span>
          ) : (
            <span className="text-muted-foreground">done</span>
          )}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t px-3 py-2">
          {item.input !== undefined && (
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-muted-foreground">
              {JSON.stringify(item.input, null, 2)}
            </pre>
          )}
          {item.result && (
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px]">
              {item.result}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function Message({ item }: { item: ChatItem }) {
  if (item.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-sm">
          {item.text}
        </div>
      </div>
    )
  }
  if (item.role === 'assistant') {
    if (!item.text && item.pending) {
      return <div className="h-5 w-10 rounded bg-muted bk-pulse" />
    }
    return (
      <div className="claude-prose text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.text || ''}</ReactMarkdown>
      </div>
    )
  }
  if (item.role === 'tool') {
    // Tool discovery is Claude's own bookkeeping, not work worth showing.
    if (item.name === 'ToolSearch') return null
    return <ToolRow item={item} />
  }
  if (item.role === 'error') {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
        <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span className="whitespace-pre-wrap">{item.text}</span>
      </div>
    )
  }
  if (item.role === 'info') {
    return <div className="text-center text-xs text-muted-foreground">{item.text}</div>
  }
  if (item.role === 'meta') {
    const parts = [
      item.durationMs ? `${(item.durationMs / 1000).toFixed(1)}s` : null,
      item.turns ? `${item.turns} step${item.turns === 1 ? '' : 's'}` : null,
      typeof item.costUsd === 'number' ? `$${item.costUsd.toFixed(3)}` : null,
    ].filter(Boolean)
    if (!parts.length) return null
    return <div className="text-[11px] text-muted-foreground/80">{parts.join('  ·  ')}</div>
  }
  return null
}

export function ClaudeChat({ compact = false }: { compact?: boolean }) {
  const { items, streaming, send, stop, conversationId, openConversation, status } = useClaudeStore()
  const [draft, setDraft] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // A persisted conversation id with no items loaded: reload it.
  // biome-ignore lint/correctness/useExhaustiveDependencies: load once per id
  useEffect(() => {
    if (conversationId && items.length === 0 && !streaming) {
      openConversation(conversationId)
    }
  }, [conversationId])

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on new content
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [items])

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [draft])

  const ready = status ? status.cli.installed && status.cli.logged_in : true

  const submit = (text?: string) => {
    const msg = (text ?? draft).trim()
    if (!msg || streaming) return
    setDraft('')
    send(msg)
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className={cn('min-h-0 flex-1 overflow-y-auto', compact ? 'px-4 py-4' : 'px-6 py-6')}>
        {items.length === 0 ? (
          <div className="flex h-full flex-col justify-end gap-4 pb-2">
            <div>
              <p className="text-sm font-medium">Ask Claude to work the desk.</p>
              <p className="mt-1 text-sm text-muted-foreground">
                It reads quotes, positions and the order book, and places orders through the platform.
              </p>
            </div>
            <div className="grid gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => submit(s)}
                  disabled={!ready}
                  className="rounded-lg border px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className={cn('mx-auto flex flex-col gap-3', !compact && 'max-w-3xl')}>
            {items.map((item) => (
              <Message key={item.id} item={item} />
            ))}
          </div>
        )}
      </div>

      <div className={cn('border-t', compact ? 'p-3' : 'px-6 py-4')}>
        <div className={cn('mx-auto', !compact && 'max-w-3xl')}>
          <div className="flex items-end gap-2 rounded-xl border bg-card px-3 py-2 focus-within:border-ring/60 focus-within:ring-2 focus-within:ring-ring/15">
            <textarea
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              rows={1}
              disabled={!ready}
              placeholder={ready ? 'Message Claude' : 'Connect Claude Code to start'}
              aria-label="Message Claude"
              className="max-h-[180px] min-h-[24px] flex-1 resize-none bg-transparent py-1 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
            />
            {streaming ? (
              <button
                type="button"
                onClick={() => stop()}
                aria-label="Stop"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-foreground text-background"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => submit()}
                disabled={!draft.trim() || !ready}
                aria-label="Send"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-foreground text-background transition-opacity disabled:opacity-30"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
