import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import ChatActionGroup from '../index'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockCreateSession = vi.fn()

vi.mock('@agentscope-ai/chat', () => ({
  useChatAnywhereSessions: () => ({ createSession: mockCreateSession }),
  // ChatSessionDrawer 内部也用了这些，一并 mock
  useChatAnywhereSessionsState: () => ({
    sessions: [],
    currentSessionId: null,
    setCurrentSessionId: vi.fn(),
    setSessions: vi.fn(),
  }),
}))

// IconButton mock：渲染真实 <button>，保留 onClick，icon 作为子元素方便定位
vi.mock('@agentscope-ai/design', () => ({
  IconButton: ({
    onClick,
    icon,
  }: {
    onClick?: () => void
    icon: React.ReactNode
  }) => <button onClick={onClick}>{icon}</button>,
}))

// 图标用 data-testid 标记，便于定位按钮
vi.mock('@agentscope-ai/icons', () => ({
  SparkNewChatFill: () => <span data-testid="icon-new-chat" />,
  SparkHistoryLine: () => <span data-testid="icon-history" />,
  SparkOperateRightLine: () => <span data-testid="icon-close" />,
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// ChatSessionDrawer mock 路径相对于测试文件，需要 ../../
vi.mock('../../ChatSessionDrawer', () => ({
  default: ({
    open,
    onClose,
  }: {
    open: boolean
    onClose: () => void
  }) =>
    open ? (
      <div data-testid="session-drawer">
        <button data-testid="drawer-close-btn" onClick={onClose}>
          close
        </button>
      </div>
    ) : null,
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getNewChatBtn() {
  return screen.getByTestId('icon-new-chat').closest('button')!
}

function getHistoryBtn() {
  return screen.getByTestId('icon-history').closest('button')!
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ChatActionGroup', () => {
  beforeEach(() => {
    mockCreateSession.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('渲染新建对话和历史记录两个按钮', () => {
    renderWithProviders(<ChatActionGroup />)
    expect(getNewChatBtn()).toBeInTheDocument()
    expect(getHistoryBtn()).toBeInTheDocument()
  })

  it('初始状态 drawer 不可见', () => {
    renderWithProviders(<ChatActionGroup />)
    expect(screen.queryByTestId('session-drawer')).not.toBeInTheDocument()
  })

  it('点击新建对话按钮调用 createSession', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatActionGroup />)

    await user.click(getNewChatBtn())

    expect(mockCreateSession).toHaveBeenCalledOnce()
  })

  it('点击历史记录按钮打开 drawer', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatActionGroup />)

    await user.click(getHistoryBtn())

    expect(screen.getByTestId('session-drawer')).toBeInTheDocument()
  })

  it('drawer 关闭后从 DOM 移除', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatActionGroup />)

    await user.click(getHistoryBtn())
    expect(screen.getByTestId('session-drawer')).toBeInTheDocument()

    await user.click(screen.getByTestId('drawer-close-btn'))
    expect(screen.queryByTestId('session-drawer')).not.toBeInTheDocument()
  })

  it('多次点击新建对话按钮，每次都调用 createSession', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatActionGroup />)

    await user.click(getNewChatBtn())
    await user.click(getNewChatBtn())

    expect(mockCreateSession).toHaveBeenCalledTimes(2)
  })
})
