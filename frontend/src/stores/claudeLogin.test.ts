/**
 * T06: the Claude store's sign-in state and actions, against a mocked API.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/claude', () => ({
  claudeApi: {
    chat: vi.fn(),
    stop: vi.fn(),
    status: vi.fn(),
    conversation: vi.fn(),
    startLogin: vi.fn(),
    loginStatus: vi.fn(),
    submitLoginCode: vi.fn(),
    cancelLogin: vi.fn(),
  },
}))

import { type ClaudeLoginState, claudeApi } from '@/api/claude'
import { useClaudeStore } from './claudeStore'

const api = claudeApi as unknown as Record<string, ReturnType<typeof vi.fn>>

const IDLE: ClaudeLoginState = {
  state: 'idle',
  url: null,
  needs_code: false,
  method: null,
  message: null,
}
const login = (over: Partial<ClaudeLoginState>): ClaudeLoginState => ({ ...IDLE, ...over })

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset()
  api.status.mockResolvedValue({
    status: 'success',
    cli: { installed: true, logged_in: true },
    login: IDLE,
  })
  useClaudeStore.setState({ status: null, login: null, loginError: null })
})

describe('claudeStore sign-in', () => {
  it('starts the subscription sign-in by default', async () => {
    api.startLogin.mockResolvedValue(login({ state: 'starting', method: 'claudeai' }))
    await useClaudeStore.getState().startLogin()
    expect(api.startLogin).toHaveBeenCalledTimes(1)
    expect([undefined, 'claudeai']).toContain(api.startLogin.mock.calls[0][0])
    expect(useClaudeStore.getState().login).toMatchObject({ state: 'starting', method: 'claudeai' })
  })

  it('starts a Console sign-in when asked', async () => {
    api.startLogin.mockResolvedValue(login({ state: 'starting', method: 'console' }))
    await useClaudeStore.getState().startLogin('console')
    expect(api.startLogin).toHaveBeenCalledWith('console')
  })

  it('a poll that reaches connected refreshes the status with force', async () => {
    api.loginStatus.mockResolvedValue(login({ state: 'connected' }))
    await useClaudeStore.getState().pollLogin()
    expect(useClaudeStore.getState().login?.state).toBe('connected')
    await vi.waitFor(() => expect(api.status).toHaveBeenCalledWith(true))
  })

  it('a poll still waiting does not refresh the status', async () => {
    api.loginStatus.mockResolvedValue(
      login({ state: 'waiting', url: 'https://claude.com/cai/oauth/authorize?x=1' })
    )
    await useClaudeStore.getState().pollLogin()
    expect(useClaudeStore.getState().login?.url).toBe('https://claude.com/cai/oauth/authorize?x=1')
    expect(api.status).not.toHaveBeenCalled()
  })

  it('starting when already signed in also refreshes the status', async () => {
    api.startLogin.mockResolvedValue(login({ state: 'connected' }))
    await useClaudeStore.getState().startLogin()
    await vi.waitFor(() => expect(api.status).toHaveBeenCalledWith(true))
  })

  it('a refusal becomes loginError, cleared by the next action', async () => {
    api.startLogin.mockRejectedValueOnce(
      new Error('Claude Code is not installed on this machine. Install it, then press Refresh.')
    )
    await useClaudeStore.getState().startLogin()
    expect(useClaudeStore.getState().loginError).toBe(
      'Claude Code is not installed on this machine. Install it, then press Refresh.'
    )
    api.loginStatus.mockResolvedValue(IDLE)
    await useClaudeStore.getState().pollLogin()
    expect(useClaudeStore.getState().loginError).toBeNull()
  })

  it('submits the code and keeps the returned state', async () => {
    api.submitLoginCode.mockResolvedValue(login({ state: 'waiting', url: 'u' }))
    await useClaudeStore.getState().submitLoginCode('abc')
    expect(api.submitLoginCode).toHaveBeenCalledWith('abc')
    expect(useClaudeStore.getState().login?.state).toBe('waiting')
  })

  it('a refused code is reported in words', async () => {
    api.submitLoginCode.mockRejectedValue(new Error('Paste the code shown after you signed in.'))
    await useClaudeStore.getState().submitLoginCode('')
    expect(useClaudeStore.getState().loginError).toBe('Paste the code shown after you signed in.')
  })

  it('cancel goes back to idle', async () => {
    useClaudeStore.setState({ login: login({ state: 'waiting', url: 'u' }) })
    api.cancelLogin.mockResolvedValue(IDLE)
    await useClaudeStore.getState().cancelLogin()
    expect(api.cancelLogin).toHaveBeenCalledTimes(1)
    expect(useClaudeStore.getState().login).toEqual(IDLE)
  })

  it('refreshStatus copies the server login state', async () => {
    const waiting = login({
      state: 'waiting',
      url: 'https://claude.com/cai/oauth/authorize?y=2',
      needs_code: true,
    })
    api.status.mockResolvedValue({
      status: 'success',
      cli: { installed: true, logged_in: false },
      login: waiting,
    })
    await useClaudeStore.getState().refreshStatus(true)
    expect(useClaudeStore.getState().login).toEqual(waiting)
  })

  it('a failing status read keeps the last login state', async () => {
    const waiting = login({ state: 'waiting', url: 'u' })
    useClaudeStore.setState({ login: waiting })
    api.status.mockRejectedValue(new Error('offline'))
    await useClaudeStore.getState().refreshStatus()
    expect(useClaudeStore.getState().login).toEqual(waiting)
  })
})
