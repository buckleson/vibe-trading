import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { claudeApi } from '@/api/claude'
import { ClaudeChat } from '@/components/claude/ClaudeChat'
import { StatusDot, useClaudeState } from '@/components/claude/ClaudePanel'
import { ConnectClaude } from '@/components/claude/ConnectClaude'
import { cn } from '@/lib/utils'
import { useClaudeStore } from '@/stores/claudeStore'

function relTime(iso?: string | null): string {
  if (!iso) return ''
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return new Date(iso).toLocaleDateString()
}

function CopyBlock({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="group relative">
      <pre className="overflow-x-auto whitespace-pre rounded-lg bg-muted px-3 py-2.5 pr-9 font-mono text-[11px] leading-relaxed">
        {text}
      </pre>
      <button
        type="button"
        aria-label={`Copy ${label}`}
        onClick={() => {
          navigator.clipboard?.writeText(text)
          setCopied(true)
          window.setTimeout(() => setCopied(false), 1500)
        }}
        className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground"
      >
        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  )
}

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean | null }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-[13px]">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex items-center gap-1.5 text-right font-medium">
        {ok !== undefined && ok !== null && (
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              ok ? 'bg-emerald-500' : 'bg-muted-foreground/40'
            )}
          />
        )}
        {value}
      </span>
    </div>
  )
}

function ConnectionPanel() {
  const { status, refreshStatus, mcpState } = useClaudeStore()
  const [refreshing, setRefreshing] = useState(false)
  const [showAllSkills, setShowAllSkills] = useState(false)
  const connect = useQuery({
    queryKey: ['claude-connect'],
    queryFn: claudeApi.connect,
    staleTime: 60_000,
  })
  const cli = status?.cli
  const ext = status?.external

  return (
    <div className="flex flex-col gap-6 overflow-y-auto p-5">
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Connection</h3>
          <button
            type="button"
            onClick={async () => {
              setRefreshing(true)
              await refreshStatus(true)
              setRefreshing(false)
            }}
            className="flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
            Refresh
          </button>
        </div>
        <div className="divide-y">
          <Row
            label="Claude Code"
            value={cli?.installed ? `v${cli.version ?? '?'}` : 'Not installed'}
            ok={cli?.installed}
          />
          <Row
            label="Signed in"
            value={
              cli?.logged_in
                ? (cli.plan?.label ?? (cli.auth_method ?? 'yes').replace('_', ' '))
                : 'No'
            }
            ok={cli?.logged_in}
          />
          <Row
            label="Platform tools"
            value={mcpState ? mcpState : status ? 'Ready' : '...'}
            ok={mcpState ? mcpState === 'connected' : status ? true : null}
          />
          <Row
            label="Terminal session"
            value={
              ext?.connected
                ? `Active ${relTime(ext.last_seen)}`
                : ext?.last_seen
                  ? `Seen ${relTime(ext.last_seen)}`
                  : 'None'
            }
            ok={ext?.connected}
          />
          <Row label="Orders" value={status?.sandbox ? 'Sandbox' : status ? 'Live' : '...'} />
          {status?.market_data && (
            <Row
              label="Prices"
              value={status.market_data.source === 'live' ? 'Live (Yahoo)' : 'Simulated'}
              ok={status.market_data.source === 'live'}
            />
          )}
        </div>
        <ConnectClaude />
      </section>

      <section>
        <h3 className="mb-1 text-sm font-semibold">Use it from your terminal</h3>
        <p className="mb-2 text-xs text-muted-foreground">
          Add the platform to Claude Code once. Any session can then trade here, and this page shows
          it as connected.
        </p>
        {connect.data ? (
          <div className="space-y-2">
            <CopyBlock label="command" text={connect.data.command} />
            <CopyBlock label="desk command" text={`cd ${connect.data.desk_dir} && claude`} />
          </div>
        ) : (
          <div className="h-16 rounded-lg bg-muted bk-pulse" />
        )}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold">Skills</h3>
        {status?.skills?.length ? (
          <ul className="flex flex-wrap gap-1.5">
            {(showAllSkills ? status.skills : status.skills.slice(0, 6)).map((s) => (
              <li
                key={s.name}
                title={s.description}
                className="rounded-md border px-2 py-0.5 text-xs text-muted-foreground"
              >
                {s.name}
              </li>
            ))}
            {status.skills.length > 6 && (
              <li>
                <button
                  type="button"
                  onClick={() => setShowAllSkills(!showAllSkills)}
                  className="rounded-md px-2 py-0.5 text-xs text-muted-foreground underline-offset-2 hover:underline"
                >
                  {showAllSkills ? 'Show fewer' : `+${status.skills.length - 6} more`}
                </button>
              </li>
            )}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">
            No skills found. Run scripts/install_claude_skills.sh.
          </p>
        )}
      </section>

      <section className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Access.</span> Trade lets Claude use the
        platform tools and web research. Full access also allows shell commands and file edits in
        the desk folder.
      </section>
    </div>
  )
}

export default function ClaudePage() {
  const {
    conversationId,
    openConversation,
    newConversation,
    streaming,
    historyVersion,
    access,
    setAccess,
    setPanelOpen,
  } = useClaudeStore()
  const { state, label, detail } = useClaudeState()
  const qc = useQueryClient()
  const history = useQuery({
    queryKey: ['claude-conversations', historyVersion],
    queryFn: claudeApi.conversations,
  })

  // The full page replaces the side panel while it is open.
  useEffect(() => {
    setPanelOpen(false)
  }, [setPanelOpen])

  return (
    <div className="-mx-4 -my-6 flex h-[calc(100vh-3.5rem)] border-t-0 lg:-mx-8">
      {/* Conversations */}
      <aside className="hidden w-60 shrink-0 flex-col border-r md:flex">
        <div className="flex h-12 items-center justify-between px-4">
          <span className="text-sm font-semibold">Conversations</span>
          <button
            type="button"
            onClick={newConversation}
            disabled={streaming}
            aria-label="New conversation"
            className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-40"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {history.data?.length ? (
            history.data.map((c) => (
              <div
                key={c.id}
                className={cn(
                  'group flex items-center rounded-md',
                  c.id === conversationId ? 'bg-accent' : 'hover:bg-accent/60'
                )}
              >
                <button
                  type="button"
                  onClick={() => openConversation(c.id)}
                  disabled={streaming}
                  className="min-w-0 flex-1 px-2.5 py-2 text-left"
                >
                  <div className="truncate text-[13px]">{c.title}</div>
                  <div className="text-[11px] text-muted-foreground">{relTime(c.updated)}</div>
                </button>
                <button
                  type="button"
                  aria-label="Delete conversation"
                  onClick={async () => {
                    await claudeApi.deleteConversation(c.id)
                    if (c.id === conversationId) newConversation()
                    qc.invalidateQueries({ queryKey: ['claude-conversations'] })
                  }}
                  className="mr-1 hidden h-6 w-6 items-center justify-center rounded text-muted-foreground hover:text-destructive group-hover:flex"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          ) : (
            <p className="px-2.5 py-2 text-xs text-muted-foreground">No conversations yet.</p>
          )}
        </div>
      </aside>

      {/* Chat */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center gap-2.5 border-b px-6">
          <StatusDot state={state} />
          <span className="text-sm font-semibold">{label}</span>
          <span className="hidden truncate text-xs text-muted-foreground sm:inline">{detail}</span>
          <select
            value={access}
            onChange={(e) => setAccess(e.target.value as 'trade' | 'full')}
            disabled={streaming}
            aria-label="Access level"
            className="ml-auto h-7 rounded-md border bg-transparent px-2 text-xs text-muted-foreground outline-none"
          >
            <option value="trade">Trade</option>
            <option value="full">Full access</option>
          </select>
        </div>
        <div className="min-h-0 flex-1">
          <ClaudeChat />
        </div>
      </section>

      {/* Connection */}
      <aside className="hidden w-80 shrink-0 border-l xl:flex">
        <ConnectionPanel />
      </aside>
    </div>
  )
}
