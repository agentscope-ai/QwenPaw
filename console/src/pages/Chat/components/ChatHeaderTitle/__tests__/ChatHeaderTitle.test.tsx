import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/common_setup'
import ChatHeaderTitle from '../index'

const { mockUseChatAnywhereSessionsState } = vi.hoisted(() => ({
  mockUseChatAnywhereSessionsState: vi.fn(),
}))

vi.mock('@agentscope-ai/chat', () => ({
  useChatAnywhereSessionsState: mockUseChatAnywhereSessionsState,
}))

describe('ChatHeaderTitle', () => {
  it('显示当前 session 的名称', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: 'sess-1', name: 'My Chat' }],
      currentSessionId: 'sess-1',
    })
    renderWithProviders(<ChatHeaderTitle />)
    expect(screen.getByText('My Chat')).toBeInTheDocument()
  })

  it('session name 为空时显示 "New Chat"', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [{ id: 'sess-1', name: '' }],
      currentSessionId: 'sess-1',
    })
    renderWithProviders(<ChatHeaderTitle />)
    expect(screen.getByText('New Chat')).toBeInTheDocument()
  })

  it('无匹配 session 时显示 "New Chat"', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [],
      currentSessionId: null,
    })
    renderWithProviders(<ChatHeaderTitle />)
    expect(screen.getByText('New Chat')).toBeInTheDocument()
  })

  it('切换 currentSessionId 后显示对应 session 名称', () => {
    mockUseChatAnywhereSessionsState.mockReturnValue({
      sessions: [
        { id: 'sess-1', name: 'Chat A' },
        { id: 'sess-2', name: 'Chat B' },
      ],
      currentSessionId: 'sess-2',
    })
    renderWithProviders(<ChatHeaderTitle />)
    expect(screen.getByText('Chat B')).toBeInTheDocument()
    expect(screen.queryByText('Chat A')).not.toBeInTheDocument()
  })
})
