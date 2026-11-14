import { Check, Copy, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { useClaudeStore } from '@/stores/claudeStore'

function CommandBlock({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative">
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

const primaryBtn =
  'rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background hover:opacity-90 disabled:opacity-40'
const textBtn =
  'text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline'

/** Install help or the one-click sign-in, shown until Claude Code is signed in. */
export function ConnectClaude({ compact = false }: { compact?: boolean }) {
  const status = useClaudeStore((s) => s.status)
  const login = useClaudeStore((s) => s.login)
  const loginError = useClaudeStore((s) => s.loginError)
  const { refreshStatus, startLogin, pollLogin, submitLoginCode, cancelLogin } = useClaudeStore()
  const [code, setCode] = useState('')

  const loginState = login?.state ?? 'idle'
  const polling = loginState === 'starting' || loginState === 'waiting'
  useEffect(() => {
    if (!polling) return
    const t = window.setInterval(() => pollLogin(), 2000)
    return () => window.clearInterval(t)
  }, [polling, pollLogin])

  if (!status || (status.cli.installed && status.cli.logged_in)) return null

  const box = cn('space-y-2 rounded-lg border', compact ? 'm-3 p-3' : 'mt-3 p-4')

  if (!status.cli.installed) {
    const { platform, commands, docs } = status.install
    return (
      <div className={box}>
        <h4 className="text-sm font-semibold">Install Claude Code</h4>
        <p className="text-xs text-muted-foreground">
          Run one of these in a terminal, then press Refresh. Any Claude plan works.
        </p>
        <CommandBlock
          label="install command"
          text={platform === 'windows' ? commands.windows : commands.unix}
        />
        <CommandBlock label="npm command" text={commands.npm} />
        <div className="flex items-center gap-3">
          <button type="button" className={primaryBtn} onClick={() => refreshStatus(true)}>
            Refresh
          </button>
          <a href={docs} target="_blank" rel="noopener noreferrer" className={textBtn}>
            Setup guide
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className={box}>
      {loginState === 'starting' && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Starting sign-in...
        </p>
      )}
      {loginState === 'waiting' && (
        <>
          {login?.url && (
            <a
              href={login.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block text-sm font-medium underline underline-offset-2"
            >
              Open the sign-in page
            </a>
          )}
          <p className="text-xs text-muted-foreground">
            Sign in with the account that has your Claude plan.
          </p>
          {login?.needs_code && (
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                submitLoginCode(code.trim())
              }}
            >
              <label className="flex-1 text-xs text-muted-foreground">
                Sign-in code
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className="mt-1 h-8 w-full rounded-md border bg-transparent px-2 font-mono text-xs text-foreground outline-none"
                />
              </label>
              <button type="submit" className={primaryBtn}>
                Submit code
              </button>
            </form>
          )}
          <button type="button" className={textBtn} onClick={() => cancelLogin()}>
            Cancel
          </button>
        </>
      )}
      {!polling && (
        <>
          <p className="text-xs text-muted-foreground">
            Connect your Claude plan (Pro, Max, Team or Enterprise) to chat and trade from here.
          </p>
          <div className="flex items-center gap-3">
            <button type="button" className={primaryBtn} onClick={() => startLogin('claudeai')}>
              Connect Claude
            </button>
            <button type="button" className={textBtn} onClick={() => startLogin('console')}>
              Use a Console API account
            </button>
          </div>
          {loginState === 'failed' && login?.message && (
            <p className="text-xs text-red-500">{login.message}</p>
          )}
        </>
      )}
      {loginError && <p className="text-xs text-red-500">{loginError}</p>}
    </div>
  )
}
