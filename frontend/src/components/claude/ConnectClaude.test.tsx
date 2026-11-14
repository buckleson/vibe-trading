/**
 * T06: the one-click Connect Claude flow and the install help.
 *
 * Runs the real component, store and API module; only fetch is stubbed, so
 * these tests pin the requests the server sees (T05's endpoint contract).
 */

import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ClaudeLoginState, ClaudeStatus } from '@/api/claude'
import { useClaudeStore } from '@/stores/claudeStore'
import { ConnectClaude } from './ConnectClaude'

const SIGN_IN_URL = 'https://claude.com/cai/oauth/authorize?code=true&client_id=abc&state=xyz'

const IDLE: ClaudeLoginState = {
  state: 'idle',
  url: null,
  needs_code: false,
  method: null,
  message: null,
}

function login(over: Partial<ClaudeLoginState> = {}): ClaudeLoginState {
  return { ...IDLE, ...over }
}

function status({
  installed = true,
  loggedIn = false,
  platform = 'linux',
  loginState = IDLE,
}: {
  installed?: boolean
  loggedIn?: boolean
  platform?: 'windows' | 'mac' | 'linux'
  loginState?: ClaudeLoginState
} = {}): ClaudeStatus {
  return {
    status: 'success',
    cli: {
      installed,
      path: installed ? '/usr/local/bin/claude' : null,
      version: installed ? '2.1.323' : null,
      logged_in: loggedIn,
      auth_method: loggedIn ? 'oauth_token' : null,
      api_provider: null,
      subscription: loggedIn ? 'max' : null,
      plan: loggedIn ? { key: 'max', label: 'Claude Max' } : { key: null, label: null },
    },
    in_app: { ready: installed && loggedIn, running: [] },
    external: { connected: false, last_seen: null, last_tool: null, calls: 0, client: null },
    connected: installed && loggedIn,
    sandbox: true,
    market_data: null,
    desk_dir: '/home/op/.buckleson/desk',
    skills: [],
    access_levels: {},
    install: {
      platform,
      commands: {
        windows: 'irm https://claude.ai/install.ps1 | iex',
        unix: 'curl -fsSL https://claude.ai/install.sh | bash',
        npm: 'npm install -g @anthropic-ai/claude-code',
      },
      docs: 'https://docs.claude.com/en/docs/claude-code/setup',
    },
    login: loginState,
  }
}

type Handler = (init: RequestInit | undefined) => { status?: number; body: unknown }
let routes: Record<string, Handler>
let fetchMock: ReturnType<typeof vi.fn>

function json(body: unknown, code = 200) {
  return new Response(JSON.stringify(body), {
    status: code,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  routes = {
    'GET /auth/csrf-token': () => ({ body: { csrf_token: 'csrf-1' } }),
    'GET /claude/api/status?refresh=1': () => ({ body: status({ loggedIn: true }) }),
    'GET /claude/api/status': () => ({ body: status() }),
  }
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${(init?.method ?? 'GET').toUpperCase()} ${String(input)}`
    const handler = routes[key]
    if (!handler) return json({ status: 'error', message: `unrouted ${key}` }, 404)
    const { status: code = 200, body } = handler(init)
    return json(body, code)
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  useClaudeStore.setState({ status: null, login: null, loginError: null })
})

function setStatus(s: ClaudeStatus, l: ClaudeLoginState | null = s.login) {
  useClaudeStore.setState({ status: s, login: l, loginError: null })
}

function calls(method: string, url: string) {
  return fetchMock.mock.calls.filter(
    ([u, init]) =>
      String(u) === url &&
      ((init as RequestInit | undefined)?.method ?? 'GET').toUpperCase() === method
  )
}

function bodyOf(call: unknown[]) {
  return JSON.parse(String((call[1] as RequestInit).body))
}

function headerOf(call: unknown[], name: string) {
  return new Headers((call[1] as RequestInit).headers).get(name)
}

describe('ConnectClaude: Claude Code missing', () => {
  it('shows the Windows installer on Windows, and npm', () => {
    setStatus(status({ installed: false, platform: 'windows' }))
    render(<ConnectClaude />)
    expect(screen.getByText('Install Claude Code')).toBeInTheDocument()
    expect(screen.getByText('irm https://claude.ai/install.ps1 | iex')).toBeInTheDocument()
    expect(screen.getByText('npm install -g @anthropic-ai/claude-code')).toBeInTheDocument()
    expect(
      screen.queryByText('curl -fsSL https://claude.ai/install.sh | bash')
    ).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect Claude' })).not.toBeInTheDocument()
  })

  it.each(['linux', 'mac'] as const)('shows the shell installer on %s', (platform) => {
    setStatus(status({ installed: false, platform }))
    render(<ConnectClaude />)
    expect(screen.getByText('curl -fsSL https://claude.ai/install.sh | bash')).toBeInTheDocument()
    expect(screen.queryByText('irm https://claude.ai/install.ps1 | iex')).not.toBeInTheDocument()
  })

  it('Refresh re-reads the status with refresh=1', async () => {
    setStatus(status({ installed: false }))
    render(<ConnectClaude />)
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(calls('GET', '/claude/api/status?refresh=1')).toHaveLength(1))
  })
})

describe('ConnectClaude: signed out', () => {
  it('Connect Claude starts the subscription sign-in', async () => {
    routes['POST /claude/api/login'] = () => ({
      body: { status: 'success', login: login({ state: 'starting', method: 'claudeai' }) },
    })
    setStatus(status())
    render(<ConnectClaude />)
    await userEvent.click(screen.getByRole('button', { name: 'Connect Claude' }))
    await waitFor(() => expect(calls('POST', '/claude/api/login')).toHaveLength(1))
    const call = calls('POST', '/claude/api/login')[0]
    expect(bodyOf(call)).toEqual({ method: 'claudeai' })
    expect(headerOf(call, 'X-CSRFToken')).toBe('csrf-1')
    expect(await screen.findByText('Starting sign-in...')).toBeInTheDocument()
  })

  it('a Console API account posts method console', async () => {
    routes['POST /claude/api/login'] = () => ({
      body: { status: 'success', login: login({ state: 'starting', method: 'console' }) },
    })
    setStatus(status())
    render(<ConnectClaude />)
    await userEvent.click(screen.getByRole('button', { name: 'Use a Console API account' }))
    await waitFor(() => expect(calls('POST', '/claude/api/login')).toHaveLength(1))
    expect(bodyOf(calls('POST', '/claude/api/login')[0])).toEqual({ method: 'console' })
  })

  it('shows the server sentence when the sign-in cannot start', async () => {
    routes['POST /claude/api/login'] = () => ({
      status: 500,
      body: {
        status: 'error',
        message:
          'Claude Code could not start the sign-in. Run claude auth login in a terminal instead.',
      },
    })
    setStatus(status())
    render(<ConnectClaude />)
    await userEvent.click(screen.getByRole('button', { name: 'Connect Claude' }))
    expect(
      await screen.findByText(
        'Claude Code could not start the sign-in. Run claude auth login in a terminal instead.'
      )
    ).toBeInTheDocument()
    expect(screen.queryByText(/500/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect Claude' })).toBeInTheDocument()
  })

  it('a failed sign-in shows its message and offers Connect again', () => {
    const failed = login({
      state: 'failed',
      message: 'Sign-in did not finish. Press Connect Claude to try again.',
    })
    setStatus(status({ loginState: failed }))
    render(<ConnectClaude />)
    expect(
      screen.getByText('Sign-in did not finish. Press Connect Claude to try again.')
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Connect Claude' })).toBeInTheDocument()
  })

  it('treats a missing login block as idle', () => {
    setStatus(status(), null)
    render(<ConnectClaude />)
    expect(screen.getByRole('button', { name: 'Connect Claude' })).toBeInTheDocument()
  })
})

describe('ConnectClaude: waiting for the operator', () => {
  const waiting = login({
    state: 'waiting',
    url: SIGN_IN_URL,
    needs_code: true,
    method: 'claudeai',
  })

  it('links to the sign-in page in a new tab', () => {
    setStatus(status({ loginState: waiting }))
    render(<ConnectClaude />)
    const link = screen.getByRole('link', { name: 'Open the sign-in page' })
    expect(link).toHaveAttribute('href', SIGN_IN_URL)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(
      screen.getByText('Sign in with the account that has your Claude plan.')
    ).toBeInTheDocument()
  })

  it('submits the pasted code', async () => {
    routes['POST /claude/api/login/code'] = () => ({ body: { status: 'success', login: waiting } })
    setStatus(status({ loginState: waiting }))
    render(<ConnectClaude />)
    await userEvent.type(screen.getByLabelText('Sign-in code'), 'abc#123')
    await userEvent.click(screen.getByRole('button', { name: 'Submit code' }))
    await waitFor(() => expect(calls('POST', '/claude/api/login/code')).toHaveLength(1))
    expect(bodyOf(calls('POST', '/claude/api/login/code')[0])).toEqual({ code: 'abc#123' })
  })

  it('shows no code box when the CLI does not ask for one', () => {
    setStatus(status({ loginState: { ...waiting, needs_code: false } }))
    render(<ConnectClaude />)
    expect(screen.queryByLabelText('Sign-in code')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the sign-in page' })).toBeInTheDocument()
  })

  it('Cancel stops the sign-in', async () => {
    routes['DELETE /claude/api/login'] = () => ({ body: { status: 'success', login: IDLE } })
    setStatus(status({ loginState: waiting }))
    render(<ConnectClaude />)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(calls('DELETE', '/claude/api/login')).toHaveLength(1))
    expect(await screen.findByRole('button', { name: 'Connect Claude' })).toBeInTheDocument()
  })
})

describe('ConnectClaude: polling', () => {
  it('polls every two seconds while starting and stops on unmount', async () => {
    vi.useFakeTimers()
    routes['GET /claude/api/login'] = () => ({
      body: { status: 'success', login: login({ state: 'starting' }) },
    })
    setStatus(status({ loginState: login({ state: 'starting' }) }))
    const { unmount } = render(<ConnectClaude />)
    expect(calls('GET', '/claude/api/login')).toHaveLength(0)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(calls('GET', '/claude/api/login').length).toBeGreaterThanOrEqual(1)
    unmount()
    const seen = calls('GET', '/claude/api/login').length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(calls('GET', '/claude/api/login')).toHaveLength(seen)
  })

  it('does not poll while idle', async () => {
    vi.useFakeTimers()
    setStatus(status())
    render(<ConnectClaude />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(calls('GET', '/claude/api/login')).toHaveLength(0)
  })

  it('reaching connected refreshes the status and the panel goes away', async () => {
    vi.useFakeTimers()
    routes['GET /claude/api/login'] = () => ({
      body: { status: 'success', login: login({ state: 'connected' }) },
    })
    const waiting = login({ state: 'waiting', url: SIGN_IN_URL })
    setStatus(status({ loginState: waiting }))
    const { container } = render(<ConnectClaude />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(calls('GET', '/claude/api/status?refresh=1').length).toBeGreaterThanOrEqual(1)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('ConnectClaude: connected', () => {
  it('renders nothing once Claude Code is signed in', () => {
    setStatus(status({ loggedIn: true }))
    const { container } = render(<ConnectClaude />)
    expect(container).toBeEmptyDOMElement()
  })

  it('does not throw before the first status arrives', () => {
    useClaudeStore.setState({ status: null, login: null })
    expect(() => render(<ConnectClaude compact />)).not.toThrow()
  })
})
