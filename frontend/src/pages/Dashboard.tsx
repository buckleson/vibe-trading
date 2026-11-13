import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ArrowUp, Plus, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { tradingApi } from '@/api/trading'
import { PlaceOrderDialog } from '@/components/trading/PlaceOrderDialog'
import { useOrderEventRefresh } from '@/hooks/useOrderEventRefresh'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useClaudeStore } from '@/stores/claudeStore'
import { onModeChange, useThemeStore } from '@/stores/themeStore'
import type { Order, Position } from '@/types/trading'

interface MarginData {
  availablecash: string
  collateral: string
  m2munrealized: string
  m2mrealized: string
  utiliseddebits: string
}

interface MasterContractStatus {
  status: 'pending' | 'downloading' | 'success' | 'error'
  message?: string
  total_symbols?: number
}

const WATCHLIST = [
  { symbol: 'NIFTY', exchange: 'NSE_INDEX', label: 'Nifty 50' },
  { symbol: 'BANKNIFTY', exchange: 'NSE_INDEX', label: 'Bank Nifty' },
  { symbol: 'SENSEX', exchange: 'BSE_INDEX', label: 'Sensex' },
  { symbol: 'RELIANCE', exchange: 'NSE', label: 'Reliance' },
  { symbol: 'HDFCBANK', exchange: 'NSE', label: 'HDFC Bank' },
  { symbol: 'INFY', exchange: 'NSE', label: 'Infosys' },
  { symbol: 'TCS', exchange: 'NSE', label: 'TCS' },
  { symbol: 'ICICIBANK', exchange: 'NSE', label: 'ICICI Bank' },
]

const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })

function num(v: string | number | undefined | null): number {
  const n = typeof v === 'string' ? Number.parseFloat(v) : (v ?? 0)
  return Number.isFinite(n) ? n : 0
}

function compactInr(v: number): string {
  const a = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  if (a >= 1e7) return `${sign}${(a / 1e7).toFixed(2)} Cr`
  if (a >= 1e5) return `${sign}${(a / 1e5).toFixed(2)} L`
  return `${sign}${inr.format(a)}`
}

function pnlClass(v: number) {
  if (v > 0) return 'text-emerald-600 dark:text-emerald-400'
  if (v < 0) return 'text-red-600 dark:text-red-400'
  return 'text-foreground'
}

function Panel({
  title,
  action,
  children,
  className,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn('rounded-xl border bg-card', className)}>
      <div className="flex h-11 items-center justify-between border-b px-4">
        <h2 className="text-[13px] font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function ViewAll({ to }: { to: string }) {
  return (
    <Link to={to} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
      View all <ArrowRight className="h-3 w-3" />
    </Link>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="px-4 py-10 text-center text-sm text-muted-foreground">{text}</div>
}

export default function Dashboard() {
  const apiKey = useAuthStore((s) => s.apiKey)
  const appMode = useThemeStore((s) => s.appMode)
  const [margin, setMargin] = useState<MarginData | null>(null)
  const [fundsError, setFundsError] = useState<string | null>(null)
  const [ticket, setTicket] = useState<{ open: boolean; symbol?: string; exchange?: string; action?: 'BUY' | 'SELL' }>({
    open: false,
  })
  const [prompt, setPrompt] = useState('')
  const { setPanelOpen, send, streaming } = useClaudeStore()
  const marketData = useClaudeStore((s) => s.status?.market_data)

  const fetchFunds = useCallback(async () => {
    try {
      const res = await fetch('/auth/dashboard-data', { credentials: 'include' })
      const data = await res.json()
      if (data.status === 'success' && data.data) {
        setMargin(data.data)
        setFundsError(null)
      } else {
        setFundsError(data.message || 'Funds are not available right now.')
      }
    } catch {
      setFundsError('Funds are not available right now.')
    }
  }, [])

  const positions = useQuery({
    queryKey: ['dash-positions', apiKey],
    queryFn: () => tradingApi.getPositions(apiKey as string),
    enabled: !!apiKey,
    refetchInterval: 10_000,
  })
  const orders = useQuery({
    queryKey: ['dash-orders', apiKey],
    queryFn: () => tradingApi.getOrders(apiKey as string),
    enabled: !!apiKey,
    refetchInterval: 15_000,
  })
  const quotes = useQuery({
    queryKey: ['dash-quotes', apiKey],
    queryFn: () =>
      tradingApi.getMultiQuotes(
        apiKey as string,
        WATCHLIST.map(({ symbol, exchange }) => ({ symbol, exchange }))
      ),
    enabled: !!apiKey,
    refetchInterval: 5_000,
  })
  const contract = useQuery({
    queryKey: ['dash-contract'],
    queryFn: async (): Promise<MasterContractStatus> => {
      const res = await fetch('/api/master-contract/status', {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      })
      return res.json()
    },
    refetchInterval: (q) => (q.state.data?.status === 'success' ? false : 3000),
  })

  useEffect(() => {
    fetchFunds()
  }, [fetchFunds])

  const refreshAll = useCallback(() => {
    fetchFunds()
    positions.refetch()
    orders.refetch()
  }, [fetchFunds, positions, orders])

  useOrderEventRefresh(refreshAll, { events: ['order_event', 'analyzer_update', 'close_position_event'] })
  useEffect(() => onModeChange(() => refreshAll()), [refreshAll])

  const posList: Position[] = (positions.data?.data ?? []).filter((p) => num(p.quantity) !== 0)
  const orderList: Order[] = [...(orders.data?.data?.orders ?? [])].reverse()
  const quoteMap = new Map(
    (quotes.data?.results ?? []).map((r) => [`${r.exchange}:${r.symbol}`, r.data] as const)
  )

  const realized = num(margin?.m2mrealized)
  const unrealized = num(margin?.m2munrealized)
  const kpis = [
    { label: 'Available', value: margin ? compactInr(num(margin.availablecash)) : '...' },
    { label: 'Realized P&L', value: margin ? compactInr(realized) : '...', cls: pnlClass(realized) },
    { label: 'Unrealized P&L', value: margin ? compactInr(unrealized) : '...', cls: pnlClass(unrealized) },
    { label: 'Margin used', value: margin ? compactInr(num(margin.utiliseddebits)) : '...' },
    { label: 'Open positions', value: positions.data ? String(posList.length) : '...' },
  ]

  const askClaude = (text: string) => {
    const t = text.trim()
    if (!t || streaming) return
    setPanelOpen(true)
    setPrompt('')
    send(t)
  }

  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <div className="@container flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Overview</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {today}
            {appMode === 'analyzer' ? ' · Sandbox: orders are simulated with sandbox capital' : ' · Live trading'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPanelOpen(true)}
            className="flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium hover:bg-accent"
          >
            <Sparkles className="h-4 w-4" />
            Ask Claude
          </button>
          <button
            type="button"
            onClick={() => setTicket({ open: true, symbol: 'RELIANCE', exchange: 'NSE', action: 'BUY' })}
            className="flex h-9 items-center gap-2 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            New order
          </button>
        </div>
      </div>

      {/* KPI strip */}
      <section className="grid grid-cols-2 overflow-hidden rounded-xl border bg-card @2xl:grid-cols-5">
        {kpis.map((k, i) => (
          <div
            key={k.label}
            className={cn(
              'flex flex-col gap-1 px-5 py-4',
              i % 2 === 1 && 'border-l',
              i >= 2 && 'border-t @2xl:border-t-0',
              i > 0 && '@2xl:border-l'
            )}
          >
            <span className="text-xs text-muted-foreground">{k.label}</span>
            <span className={cn('text-xl font-semibold tabular-nums tracking-tight', k.cls)}>{k.value}</span>
          </div>
        ))}
      </section>
      {fundsError && <p className="-mt-3 text-xs text-destructive">{fundsError}</p>}

      <div className="grid gap-6 @5xl:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-6 @5xl:col-span-2">
          <Panel title="Positions" action={<ViewAll to="/positions" />}>
            {posList.length === 0 ? (
              <Empty text="No open positions. Place an order or ask Claude to take a trade." />
            ) : (
              <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground">
                    <th className="px-4 py-2 text-left font-medium">Symbol</th>
                    <th className="px-4 py-2 text-left font-medium">Product</th>
                    <th className="px-4 py-2 text-right font-medium">Qty</th>
                    <th className="px-4 py-2 text-right font-medium">Avg</th>
                    <th className="px-4 py-2 text-right font-medium">LTP</th>
                    <th className="px-4 py-2 text-right font-medium">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {posList.slice(0, 6).map((p) => (
                    <tr key={`${p.exchange}:${p.symbol}:${p.product}`} className="border-t">
                      <td className="px-4 py-2.5">
                        <div className="font-medium">{p.symbol}</div>
                        <div className="text-[11px] text-muted-foreground">{p.exchange}</div>
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground">{p.product}</td>
                      <td className={cn('px-4 py-2.5 text-right tabular-nums', num(p.quantity) < 0 && 'text-red-600 dark:text-red-400')}>
                        {p.quantity}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{inr.format(num(p.average_price))}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{inr.format(num(p.ltp))}</td>
                      <td className={cn('px-4 py-2.5 text-right font-medium tabular-nums', pnlClass(num(p.pnl)))}>
                        {inr.format(num(p.pnl))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
          </Panel>

          <Panel title="Recent orders" action={<ViewAll to="/orderbook" />}>
            {orderList.length === 0 ? (
              <Empty text="No orders today." />
            ) : (
              <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground">
                    <th className="px-4 py-2 text-left font-medium">Time</th>
                    <th className="px-4 py-2 text-left font-medium">Symbol</th>
                    <th className="px-4 py-2 text-left font-medium">Side</th>
                    <th className="px-4 py-2 text-right font-medium">Qty</th>
                    <th className="px-4 py-2 text-right font-medium">Price</th>
                    <th className="px-4 py-2 text-right font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {orderList.slice(0, 6).map((o) => (
                    <tr key={o.orderid} className="border-t">
                      <td className="px-4 py-2.5 text-muted-foreground tabular-nums">
                        {String(o.timestamp).split(' ').pop()}
                      </td>
                      <td className="px-4 py-2.5 font-medium">{o.symbol}</td>
                      <td className={cn('px-4 py-2.5 text-xs font-semibold', o.action === 'BUY' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
                        {o.action}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{o.quantity}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{inr.format(num(o.price))}</td>
                      <td className="px-4 py-2.5 text-right">
                        <span
                          className={cn(
                            'rounded-md px-1.5 py-0.5 text-[11px] font-medium capitalize',
                            o.order_status === 'complete'
                              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                              : o.order_status === 'rejected' || o.order_status === 'cancelled'
                                ? 'bg-red-500/10 text-red-600 dark:text-red-400'
                                : 'bg-muted text-muted-foreground'
                          )}
                        >
                          {o.order_status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
          </Panel>
        </div>

        <div className="flex flex-col gap-6">
          <Panel
            title="Market watch"
            action={
              marketData ? (
                <span
                  title={marketData.message}
                  className={cn(
                    'rounded-md px-1.5 py-0.5 text-[11px] font-medium',
                    marketData.source === 'live'
                      ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                      : 'bg-sandbox/10 text-sandbox'
                  )}
                >
                  {marketData.source === 'live' ? 'Live prices' : 'Simulated prices'}
                </span>
              ) : (
                <span className="text-[11px] text-muted-foreground">Hover a row to trade</span>
              )
            }
          >
            <ul>
              {WATCHLIST.map((w, i) => {
                const q = quoteMap.get(`${w.exchange}:${w.symbol}`)
                const ltp = num(q?.ltp)
                const prev = num(q?.prev_close)
                const chg = prev ? ((ltp - prev) / prev) * 100 : 0
                const tradable = !w.exchange.endsWith('_INDEX')
                return (
                  <li key={w.symbol} className={cn('group flex items-center gap-3 px-4 py-2.5', i > 0 && 'border-t')}>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{w.label}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {w.symbol} · {w.exchange}
                      </div>
                    </div>
                    {tradable && (
                      <div className="hidden gap-1 group-hover:flex">
                        <button
                          type="button"
                          onClick={() => setTicket({ open: true, symbol: w.symbol, exchange: w.exchange, action: 'BUY' })}
                          className="h-6 rounded-md bg-emerald-500/15 px-2 text-[11px] font-semibold text-emerald-600 hover:bg-emerald-500/25 dark:text-emerald-400"
                        >
                          Buy
                        </button>
                        <button
                          type="button"
                          onClick={() => setTicket({ open: true, symbol: w.symbol, exchange: w.exchange, action: 'SELL' })}
                          className="h-6 rounded-md bg-red-500/15 px-2 text-[11px] font-semibold text-red-600 hover:bg-red-500/25 dark:text-red-400"
                        >
                          Sell
                        </button>
                      </div>
                    )}
                    <div className="text-right">
                      <div className="text-sm font-medium tabular-nums">{q ? inr.format(ltp) : '...'}</div>
                      <div className={cn('text-[11px] tabular-nums', pnlClass(chg))}>
                        {q ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : ''}
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </Panel>

          <Panel title="Ask Claude">
            <div className="p-4">
              <div className="flex items-end gap-2 rounded-lg border bg-background px-3 py-2 focus-within:border-ring/60">
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      askClaude(prompt)
                    }
                  }}
                  rows={2}
                  placeholder="e.g. Short 1 lot of NIFTY ATM call with a 30% stop"
                  aria-label="Ask Claude"
                  className="flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                />
                <button
                  type="button"
                  onClick={() => askClaude(prompt)}
                  disabled={!prompt.trim() || streaming}
                  aria-label="Send to Claude"
                  className="flex h-7 w-7 items-center justify-center rounded-md bg-foreground text-background disabled:opacity-30"
                >
                  <ArrowUp className="h-4 w-4" />
                </button>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {['Review my positions', 'Market news today', 'Square off everything'].map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => askClaude(s)}
                    className="rounded-md border px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </Panel>

          <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                contract.data?.status === 'success'
                  ? 'bg-emerald-500'
                  : contract.data?.status === 'error'
                    ? 'bg-red-500'
                    : 'bg-amber-500 bk-pulse'
              )}
            />
            {contract.data?.status === 'success'
              ? `Symbols ready (${contract.data.total_symbols ?? 0})`
              : contract.data?.status === 'error'
                ? 'Symbol download failed'
                : 'Loading symbols'}
          </div>
        </div>
      </div>

      <PlaceOrderDialog
        open={ticket.open}
        onOpenChange={(open) => setTicket((t) => ({ ...t, open }))}
        symbol={ticket.symbol}
        exchange={ticket.exchange}
        action={ticket.action}
        strategy="Buckleson"
        onSuccess={() => refreshAll()}
      />
    </div>
  )
}
