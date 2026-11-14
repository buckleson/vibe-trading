import { Maximize2, Plus, X } from 'lucide-react'
import { useEffect } from 'react'
import { Link } from 'react-router'
import { cn } from '@/lib/utils'
import { useClaudeStore } from '@/stores/claudeStore'
import { ClaudeChat } from './ClaudeChat'
import { ConnectClaude } from './ConnectClaude'

/** Poll the bridge status while the app is open. */
export function useClaudeStatusPolling(intervalMs = 15000) {
  const refreshStatus = useClaudeStore((s) => s.refreshStatus)
  useEffect(() => {
    refreshStatus()
    const t = window.setInterval(() => refreshStatus(), intervalMs)
    return () => window.clearInterval(t)
  }, [refreshStatus, intervalMs])
}

export type ClaudeState = 'connected' | 'external' | 'busy' | 'signed-out' | 'missing' | 'unknown'

export function useClaudeState(): { state: ClaudeState; label: string; detail: string } {
  const status = useClaudeStore((s) => s.status)
  const streaming = useClaudeStore((s) => s.streaming)
  if (!status) return { state: 'unknown', label: 'Claude', detail: 'Checking Claude Code' }
  if (streaming) return { state: 'busy', label: 'Claude working', detail: 'Answering now' }
  const { cli, external } = status
  if (cli.installed && cli.logged_in) {
    return {
      state: 'connected',
      label: 'Claude connected',
      detail:
        `${cli.plan?.label ?? 'Claude Code'} · v${cli.version ?? ''}${external.connected ? ' · terminal session active' : ''}`.trim(),
    }
  }
  if (external.connected) {
    return { state: 'external', label: 'Claude connected', detail: 'Terminal session over MCP' }
  }
  if (cli.installed)
    return { state: 'signed-out', label: 'Claude signed out', detail: 'Press Connect Claude' }
  return { state: 'missing', label: 'Claude offline', detail: 'Claude Code is not installed' }
}

export function StatusDot({ state, className }: { state: ClaudeState; className?: string }) {
  return (
    <span className={cn('relative inline-flex h-2 w-2 shrink-0', className)}>
      {(state === 'connected' || state === 'external' || state === 'busy') && (
        <span
          className={cn(
            'absolute inset-0 rounded-full opacity-60',
            state === 'busy'
              ? 'bg-foreground bk-pulse'
              : 'bg-emerald-500 animate-ping [animation-duration:2.4s]'
          )}
        />
      )}
      <span
        className={cn(
          'relative inline-flex h-2 w-2 rounded-full',
          state === 'connected' || state === 'external'
            ? 'bg-emerald-500'
            : state === 'busy'
              ? 'bg-foreground/70 bk-pulse'
              : state === 'signed-out'
                ? 'bg-amber-500'
                : 'bg-muted-foreground/50'
        )}
      />
    </span>
  )
}

/** Top bar control: the connection state; opens the side panel. */
export function ClaudeStatusPill() {
  const { state, label, detail } = useClaudeState()
  const togglePanel = useClaudeStore((s) => s.togglePanel)
  const panelOpen = useClaudeStore((s) => s.panelOpen)
  return (
    <button
      type="button"
      onClick={togglePanel}
      title={`${detail}. Press Ctrl+J to toggle.`}
      aria-pressed={panelOpen}
      className={cn(
        'flex h-8 items-center gap-2 rounded-full border px-3 text-xs font-medium transition-colors',
        panelOpen
          ? 'border-foreground/20 bg-accent text-foreground'
          : 'text-muted-foreground hover:text-foreground hover:bg-accent'
      )}
    >
      <StatusDot state={state} />
      <span className="hidden sm:inline">{label}</span>
      <span className="sm:hidden">Claude</span>
    </button>
  )
}

/** The docked panel beside every page. */
export function ClaudePanel() {
  const { panelOpen, setPanelOpen, newConversation, access, setAccess, streaming, mcpState } =
    useClaudeStore()
  const { state, label, detail } = useClaudeState()

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') {
        e.preventDefault()
        useClaudeStore.getState().togglePanel()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!panelOpen) return null

  return (
    <aside
      aria-label="Claude"
      className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l bg-background sm:w-[420px] lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:w-[400px] xl:w-[440px]"
    >
      <div className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
        <StatusDot state={state} />
        <div className="min-w-0">
          <div className="text-sm font-semibold leading-tight">
            {state === 'busy' ? 'Claude' : label}
          </div>
          <div className="truncate text-[11px] leading-tight text-muted-foreground">
            {mcpState && mcpState !== 'connected' ? `Platform tools: ${mcpState}` : detail}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <select
            value={access}
            onChange={(e) => setAccess(e.target.value as 'trade' | 'full')}
            disabled={streaming}
            aria-label="Access level"
            title="Trade: platform tools and web research. Full access: also shell commands and file edits."
            className="h-7 rounded-md border bg-transparent px-1.5 text-xs text-muted-foreground outline-none"
          >
            <option value="trade">Trade</option>
            <option value="full">Full access</option>
          </select>
          <button
            type="button"
            onClick={newConversation}
            disabled={streaming}
            title="New conversation"
            aria-label="New conversation"
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
          >
            <Plus className="h-4 w-4" />
          </button>
          <Link
            to="/claude"
            title="Open full page"
            aria-label="Open full page"
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </Link>
          <button
            type="button"
            onClick={() => setPanelOpen(false)}
            title="Close (Ctrl+J)"
            aria-label="Close Claude panel"
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
      {(state === 'signed-out' || state === 'missing') && <ConnectClaude compact />}
      <div className="min-h-0 flex-1">
        <ClaudeChat compact />
      </div>
    </aside>
  )
}
