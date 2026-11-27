import { useState } from 'react'
import { claudeApi } from '@/api/claude'
import { CopyBlock } from '@/components/claude/CopyBlock'
import { Button } from '@/components/ui/button'
import { useClaudeStore } from '@/stores/claudeStore'

/** Zerodha's hosted Kite MCP server: add it to Claude Code once, read-only in the app. */
export function KiteMcp() {
  const { status, refreshStatus } = useClaudeStore()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const kite = status?.kite_mcp
  if (!kite) return null

  const run = async (call: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await call()
      await refreshStatus(true)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Zerodha Kite MCP</h3>
        <span className="text-xs text-muted-foreground">{kite.added ? 'Added' : 'Not added'}</span>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        Zerodha&apos;s own MCP server gives Claude a read-only view of your Zerodha account:
        holdings, positions, margins, orders and GTTs. Claude asks you to open a Kite login link the
        first time. Orders still go through Buckleson, so Sandbox and Live apply.
      </p>
      {kite.added ? (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => run(claudeApi.removeKiteMcp)}
        >
          {busy ? 'Removing...' : 'Remove from Claude Code'}
        </Button>
      ) : (
        <div className="space-y-2">
          <Button
            size="sm"
            disabled={busy || !status?.cli.installed}
            onClick={() => run(claudeApi.addKiteMcp)}
          >
            {busy ? 'Adding...' : 'Add to Claude Code'}
          </Button>
          <CopyBlock label="Kite MCP command" text={kite.command} />
        </div>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
    </section>
  )
}
