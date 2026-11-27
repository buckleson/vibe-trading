import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/claude', () => ({
  claudeApi: { addKiteMcp: vi.fn(), removeKiteMcp: vi.fn(), status: vi.fn() },
}))

import { type ClaudeStatus, claudeApi } from '@/api/claude'
import { useClaudeStore } from '@/stores/claudeStore'
import { KiteMcp } from './KiteMcp'

const api = claudeApi as unknown as Record<string, ReturnType<typeof vi.fn>>
const URL = 'https://mcp.kite.trade/mcp'

function status(added: boolean, installed = true): ClaudeStatus {
  return {
    cli: { installed },
    kite_mcp: {
      name: 'kite',
      url: URL,
      added,
      configured_url: added ? URL : null,
      command: `claude mcp add --transport http --scope user kite ${URL}`,
      read_only: true,
    },
  } as unknown as ClaudeStatus
}

describe('Zerodha Kite MCP card', () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset()
  })

  it('renders nothing until the status is known', () => {
    useClaudeStore.setState({ status: null })
    const { container } = render(<KiteMcp />)
    expect(container).toBeEmptyDOMElement()
  })

  it('offers to add it, with the terminal command as a fallback', () => {
    useClaudeStore.setState({ status: status(false) })
    render(<KiteMcp />)
    expect(screen.getByText('Not added')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to Claude Code' })).toBeEnabled()
    expect(
      screen.getByText(`claude mcp add --transport http --scope user kite ${URL}`)
    ).toBeInTheDocument()
    expect(screen.getByText(/read-only view of your Zerodha account/)).toBeInTheDocument()
  })

  it('cannot add it without Claude Code installed', () => {
    useClaudeStore.setState({ status: status(false, false) })
    render(<KiteMcp />)
    expect(screen.getByRole('button', { name: 'Add to Claude Code' })).toBeDisabled()
  })

  it('adds it and refreshes the status', async () => {
    useClaudeStore.setState({ status: status(false) })
    api.addKiteMcp.mockResolvedValue(status(true).kite_mcp)
    api.status.mockResolvedValue(status(true))
    render(<KiteMcp />)
    await userEvent.click(screen.getByRole('button', { name: 'Add to Claude Code' }))
    expect(api.addKiteMcp).toHaveBeenCalledOnce()
    await waitFor(() => expect(screen.getByText('Added')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Remove from Claude Code' })).toBeInTheDocument()
  })

  it('removes it', async () => {
    useClaudeStore.setState({ status: status(true) })
    api.removeKiteMcp.mockResolvedValue(status(false).kite_mcp)
    api.status.mockResolvedValue(status(false))
    render(<KiteMcp />)
    await userEvent.click(screen.getByRole('button', { name: 'Remove from Claude Code' }))
    expect(api.removeKiteMcp).toHaveBeenCalledOnce()
    await waitFor(() => expect(screen.getByText('Not added')).toBeInTheDocument())
  })

  it('shows the error when Claude Code refuses', async () => {
    useClaudeStore.setState({ status: status(false) })
    api.addKiteMcp.mockRejectedValue(new Error('claude mcp add failed'))
    render(<KiteMcp />)
    await userEvent.click(screen.getByRole('button', { name: 'Add to Claude Code' }))
    expect(await screen.findByText('claude mcp add failed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to Claude Code' })).toBeEnabled()
  })
})
