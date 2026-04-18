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
  // ChatSessionDrawer internally uses these too, mock them here as well
  useChatAnywhereSessionsState: () => ({
    sessions: [],
    currentSessionId: null,
    setCurrentSessionId: vi.fn(),
    setSessions: vi.fn(),
  }),
}))

// IconButton mock: renders a real <button>, preserves onClick, icon as child for easy targeting
vi.mock('@agentscope-ai/design', () => ({
  IconButton: ({
    onClick,
    icon,
  }: {
    onClick?: () => void
    icon: React.ReactNode
  }) => <button onClick={onClick}>{icon}</button>,
}))

// Icons marked with data-testid for easy button targeting
vi.mock('@agentscope-ai/icons', () => ({
  SparkNewChatFill: () => <span data-testid="icon-new-chat" />,
  SparkHistoryLine: () => <span data-testid="icon-history" />,
  SparkOperateRightLine: () => <span data-testid="icon-close" />,
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// ChatSessionDrawer mock path is relative to the test file, needs ../../
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

  it('renders new chat and history buttons', () => {
    renderWithProviders(<ChatActionGroup />)
    expect(getNewChatBtn()).toBeInTheDocument()
    expect(getHistoryBtn()).toBeInTheDocument()
  })

  it('drawer is not visible in initial state', () => {
    renderWithProviders(<ChatActionGroup />)
    expect(screen.queryByTestId('session-drawer')).not.toBeInTheDocument()
  })

  it('clicking the new chat button calls createSession', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatActionGroup />)

    await user.click(getNewChatBtn())

    expect(mockCreateSession).toHaveBeenCalledOnce()
  })

  it('clicking the history button opens the drawer', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatActionGroup />)

    await user.click(getHistoryBtn())

    expect(screen.getByTestId('session-drawer')).toBeInTheDocument()
  })

  it('drawer is removed from the DOM after closing', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatActionGroup />)

    await user.click(getHistoryBtn())
    expect(screen.getByTestId('session-drawer')).toBeInTheDocument()

    await user.click(screen.getByTestId('drawer-close-btn'))
    expect(screen.queryByTestId('session-drawer')).not.toBeInTheDocument()
  })

  it('clicking new chat button multiple times calls createSession each time', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChatActionGroup />)

    await user.click(getNewChatBtn())
    await user.click(getNewChatBtn())

    expect(mockCreateSession).toHaveBeenCalledTimes(2)
  })
})
