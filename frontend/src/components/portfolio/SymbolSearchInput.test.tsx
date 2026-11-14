/**
 * T03: the portfolio symbol search reads the instrument master through
 * /search/api/search, not the deleted /chartink/search endpoint.
 */

import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderWithQuery } from '@/test/queryRender'
import { SymbolSearchInput } from './SymbolSearchInput'
import source from './SymbolSearchInput.tsx?raw'

const RELIANCE = {
  brexchange: 'NSE',
  brsymbol: 'RELIANCE',
  exchange: 'NSE',
  expiry: '',
  instrumenttype: 'EQ',
  lotsize: 1,
  name: 'Reliance Industries',
  strike: 0,
  symbol: 'RELIANCE',
  token: '100073',
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/search/api/search')) {
      const q = new URL(url, 'http://localhost').searchParams.get('q') ?? ''
      return jsonResponse({ results: 'RELIANCE'.startsWith(q) ? [RELIANCE] : [], total: 1 })
    }
    return jsonResponse({}, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function searchCalls() {
  return fetchMock.mock.calls.filter(([u]) => String(u).startsWith('/search/api/search'))
}

describe('SymbolSearchInput', () => {
  it('queries /search/api/search with the query and exchange and lists the result', async () => {
    renderWithQuery(<SymbolSearchInput value="" exchange="NSE" onSelect={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText('Search symbol'), 'rel')

    expect(await screen.findByText('RELIANCE')).toBeInTheDocument()
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument()

    const [url, init] = searchCalls().at(-1) ?? []
    expect(String(url)).toBe('/search/api/search?q=REL&exchange=NSE')
    expect(init).toMatchObject({ credentials: 'include' })
    expect(new Headers((init as RequestInit).headers).get('Accept')).toBe('application/json')
  })

  it('passes the exchange the parent picked', async () => {
    renderWithQuery(<SymbolSearchInput value="" exchange="BSE" onSelect={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText('Search symbol'), 'RE')
    await waitFor(() => expect(searchCalls().length).toBeGreaterThan(0))
    expect(String(searchCalls().at(-1)?.[0])).toBe('/search/api/search?q=RE&exchange=BSE')
  })

  it('encodes characters a symbol can carry', async () => {
    renderWithQuery(<SymbolSearchInput value="" exchange="NSE" onSelect={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText('Search symbol'), 'M&M')
    await waitFor(() => expect(searchCalls().length).toBeGreaterThan(0))
    expect(String(searchCalls().at(-1)?.[0])).toBe('/search/api/search?q=M%26M&exchange=NSE')
  })

  it('does not search on a single character', async () => {
    renderWithQuery(<SymbolSearchInput value="" exchange="NSE" onSelect={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText('Search symbol'), 'R')
    await new Promise((r) => setTimeout(r, 50))
    expect(searchCalls()).toHaveLength(0)
  })

  it('says nothing matched when the master has no such symbol', async () => {
    renderWithQuery(<SymbolSearchInput value="" exchange="NSE" onSelect={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText('Search symbol'), 'ZZ')
    expect(await screen.findByText(/Nothing on NSE matching/)).toBeInTheDocument()
  })

  it('treats a missing results field as no results', async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ total: 0 }))
    renderWithQuery(<SymbolSearchInput value="" exchange="NSE" onSelect={() => {}} />)
    await userEvent.type(screen.getByPlaceholderText('Search symbol'), 'RE')
    expect(await screen.findByText(/Nothing on NSE matching/)).toBeInTheDocument()
  })

  it('selects a result with the mouse', async () => {
    const onSelect = vi.fn()
    renderWithQuery(<SymbolSearchInput value="" exchange="NSE" onSelect={onSelect} />)
    await userEvent.type(screen.getByPlaceholderText('Search symbol'), 'REL')
    const option = await screen.findByText('RELIANCE')
    fireEvent.mouseDown(option)
    expect(onSelect).toHaveBeenCalledWith('RELIANCE')
  })

  it('takes an exact ticker on Enter without waiting for the list', async () => {
    const onSelect = vi.fn()
    renderWithQuery(<SymbolSearchInput value="" exchange="NSE" onSelect={onSelect} />)
    await userEvent.type(screen.getByPlaceholderText('Search symbol'), 'tcs{Enter}')
    expect(onSelect).toHaveBeenCalledWith('TCS')
  })

  it('no longer depends on the Chartink API', () => {
    expect(source).not.toMatch(/chartink/i)
    expect(source).toContain('/search/api/search')
  })
})
