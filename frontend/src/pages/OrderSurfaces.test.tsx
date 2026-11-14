/**
 * T09: every UI order surface works in Sandbox mode outside market hours.
 *
 * - The order ticket (dashboard, option chain, /trading) defaults to CNC for
 *   NSE/BSE equity and NRML for F&O, so an order placed after 15:15 IST fills
 *   instead of being refused as MIS; MIS stays selectable.
 * - A refused order shows the server's sentence, never a status code.
 * - Positions, Orderbook and the scalping terminal post to their session
 *   routes with the CSRF header (the request reaches the transport: an axios
 *   adapter records it).
 * - The scalping terminal never defaults to CNC.
 */

import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { webClient } from '@/api/client'
import { scalpingApi } from '@/api/scalping'
import { tradingApi } from '@/api/trading'
import { PlaceOrderDialog } from '@/components/trading/PlaceOrderDialog'
import { render, screen, userEvent, waitFor } from '@/test/test-utils'
import { showToast } from '@/utils/toast'
import optionChainSource from './OptionChain.tsx?raw'
import scalpingSource from './Scalping.tsx?raw'

vi.mock('@/utils/toast', () => ({
  showToast: { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/stores/authStore', () => ({
  useAuthStore: () => ({ apiKey: 'test-api-key' }),
}))

vi.mock('@/hooks/useLiveQuote', () => ({
  useLiveQuote: () => ({
    data: {
      ltp: 950,
      close: 946,
      change: 4,
      changePercent: 0.4,
      bidPrice: 949.9,
      askPrice: 950.1,
      bidSize: 10,
      askSize: 10,
    },
    isLive: false,
    isConnected: false,
    isLoading: false,
    isPaused: false,
    isFallbackMode: false,
    dataSource: 'none',
    refresh: async () => {},
  }),
}))

const ticket = {
  open: true,
  onOpenChange: () => {},
  action: 'BUY' as const,
  quantity: 1,
  lotSize: 1,
  tickSize: 0.05,
  priceType: 'MARKET' as const,
  strategy: 'Buckleson',
}

async function placeFrom(props: Record<string, unknown>) {
  const place = vi.fn(async (_order: Record<string, unknown>) => ({ orderId: 'ORD-1' }))
  render(<PlaceOrderDialog {...ticket} {...props} place={place} />)
  await userEvent.click(screen.getByRole('button', { name: /Place BUY Order/ }))
  await waitFor(() => expect(place).toHaveBeenCalledTimes(1))
  return place.mock.calls[0][0]
}

describe('order ticket product defaults', () => {
  it.each([
    ['SBIN', 'NSE', 'CNC'],
    ['RELIANCE', 'BSE', 'CNC'],
    ['NIFTY17NOV2626000CE', 'NFO', 'NRML'],
    ['SENSEX17NOV2685000PE', 'BFO', 'NRML'],
    ['NIFTY24NOV26FUT', 'NFO', 'NRML'],
  ])('%s on %s defaults to %s', async (symbol, exchange, product) => {
    const order = await placeFrom({ symbol, exchange, quantity: exchange.endsWith('FO') ? 65 : 1 })
    expect(order).toMatchObject({ symbol, exchange, product })
  })

  it('keeps MIS when the caller asks for it', async () => {
    const order = await placeFrom({ symbol: 'SBIN', exchange: 'NSE', product: 'MIS' })
    expect(order.product).toBe('MIS')
  })

  it('never sends CNC for F&O even if a caller passes it', async () => {
    const order = await placeFrom({
      symbol: 'NIFTY24NOV26FUT',
      exchange: 'NFO',
      product: 'CNC',
      quantity: 65,
    })
    expect(order.product).toBe('NRML')
  })

  it('never sends NRML for equity even if a caller passes it', async () => {
    const order = await placeFrom({ symbol: 'SBIN', exchange: 'NSE', product: 'NRML' })
    expect(order.product).toBe('CNC')
  })
})

describe('order ticket refusals', () => {
  const MIS_REFUSAL =
    'MIS orders cannot be placed after square-off time (15:15 IST). Trading resumes at 09:00 AM IST.'

  beforeEach(() => vi.mocked(showToast.error).mockReset())
  afterEach(() => vi.restoreAllMocks())

  it('shows the server sentence for a refused API order', async () => {
    vi.spyOn(tradingApi, 'placeOrder').mockResolvedValue({
      status: 'error',
      message: MIS_REFUSAL,
    } as never)
    const onError = vi.fn()
    render(
      <PlaceOrderDialog {...ticket} symbol="SBIN" exchange="NSE" product="MIS" onError={onError} />
    )
    await userEvent.click(screen.getByRole('button', { name: /Place BUY Order/ }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith(MIS_REFUSAL))
    expect(showToast.error).toHaveBeenCalledWith(MIS_REFUSAL, 'orders')
  })

  it('shows the server sentence from an HTTP 400, not the status code', async () => {
    const err = Object.assign(new Error('Request failed with status code 400'), {
      response: { status: 400, data: { status: 'error', message: MIS_REFUSAL } },
    })
    vi.spyOn(tradingApi, 'placeOrder').mockRejectedValue(err)
    render(<PlaceOrderDialog {...ticket} symbol="SBIN" exchange="NSE" product="MIS" />)
    await userEvent.click(screen.getByRole('button', { name: /Place BUY Order/ }))
    await waitFor(() => expect(showToast.error).toHaveBeenCalled())
    const shown = vi.mocked(showToast.error).mock.calls[0][0]
    expect(shown).toBe(MIS_REFUSAL)
    expect(shown).not.toMatch(/400|status code/)
  })
})

// --------------------------------------------------------------------------- #
// Session routes: what reaches the transport
// --------------------------------------------------------------------------- #

interface Sent {
  method: string
  url: string
  csrf: string | undefined
  body: unknown
}

let sent: Sent[]
let savedAdapter: InternalAxiosRequestConfig['adapter']

beforeEach(() => {
  sent = []
  savedAdapter = webClient.defaults.adapter
  const adapter: AxiosAdapter = async (config) => {
    sent.push({
      method: (config.method ?? 'get').toUpperCase(),
      url: config.url ?? '',
      csrf: config.headers?.['X-CSRFToken'] as string | undefined,
      body: typeof config.data === 'string' ? JSON.parse(config.data) : config.data,
    })
    return {
      data: { status: 'success', mode: 'analyze' },
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
      request: {},
    }
  }
  webClient.defaults.adapter = adapter
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ csrf_token: 'csrf-xyz' }), { status: 200 }))
  )
})

afterEach(() => {
  webClient.defaults.adapter = savedAdapter
  vi.unstubAllGlobals()
})

describe('Positions, Orderbook and scalping session routes', () => {
  it('close one position posts /close_position with CSRF', async () => {
    await tradingApi.closePosition('SBIN', 'NSE', 'CNC')
    expect(sent).toEqual([
      {
        method: 'POST',
        url: '/close_position',
        csrf: 'csrf-xyz',
        body: { symbol: 'SBIN', exchange: 'NSE', product: 'CNC' },
      },
    ])
  })

  it('close all posts /close_all_positions with CSRF', async () => {
    await tradingApi.closeAllPositions()
    expect(sent.map((s) => [s.method, s.url, s.csrf])).toEqual([
      ['POST', '/close_all_positions', 'csrf-xyz'],
    ])
  })

  it('cancel posts /cancel_order with the order id and CSRF', async () => {
    await tradingApi.cancelOrder('26111408267525')
    expect(sent).toEqual([
      {
        method: 'POST',
        url: '/cancel_order',
        csrf: 'csrf-xyz',
        body: { orderid: '26111408267525' },
      },
    ])
  })

  it('modify posts /modify_order with the new quantity and price and CSRF', async () => {
    await tradingApi.modifyOrder('26111408267525', {
      symbol: 'SBIN',
      exchange: 'NSE',
      action: 'BUY',
      product: 'CNC',
      pricetype: 'LIMIT',
      quantity: 2,
      price: 430.5,
    })
    expect(sent[0]).toMatchObject({
      method: 'POST',
      url: '/modify_order',
      csrf: 'csrf-xyz',
      body: {
        orderid: '26111408267525',
        quantity: 2,
        price: 430.5,
        product: 'CNC',
        pricetype: 'LIMIT',
      },
    })
  })

  it('cancel all posts /cancel_all_orders with CSRF', async () => {
    await tradingApi.cancelAllOrders()
    expect(sent.map((s) => [s.method, s.url, s.csrf])).toEqual([
      ['POST', '/cancel_all_orders', 'csrf-xyz'],
    ])
  })

  it('the scalping hotkey path posts /scalping/api/order with CSRF', async () => {
    await scalpingApi.placeOrder({
      symbol: 'NIFTY17NOV2626650CE',
      exchange: 'NFO',
      action: 'BUY',
      product: 'NRML',
      quantity: 65,
    } as never)
    expect(sent[0]).toMatchObject({
      method: 'POST',
      url: '/scalping/api/order',
      csrf: 'csrf-xyz',
      body: { product: 'NRML', exchange: 'NFO' },
    })
  })

  it('no request is sent without a CSRF token', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ csrf_token: '' }), { status: 200 }))
    )
    await expect(tradingApi.closeAllPositions()).rejects.toThrow()
    expect(sent).toEqual([])
  })
})

describe('scalping and option chain defaults', () => {
  it('scalping never defaults the product to CNC', () => {
    expect(scalpingSource).toMatch(/useState<ScalpingProduct>\(\s*'NRML'\s*\)/)
    expect(scalpingSource).not.toMatch(/setProduct\(\s*'CNC'\s*\)/)
    expect(scalpingSource).not.toMatch(/\?\s*'CNC'\s*:/)
  })

  it('the option chain ticket lets the exchange pick the product (NRML on NFO)', () => {
    const ticketProps = optionChainSource.slice(optionChainSource.indexOf('<PlaceOrderDialog'))
    expect(ticketProps).not.toMatch(/product=\{?["']?(CNC|MIS)/)
    expect(ticketProps).toMatch(/symbol=\{orderDialog\?\.symbol\}/)
  })
})
