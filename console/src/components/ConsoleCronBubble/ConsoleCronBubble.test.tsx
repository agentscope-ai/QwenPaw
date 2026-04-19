import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import ConsoleCronBubble from './index'

const { mockGetPushMessages } = vi.hoisted(() => ({
  mockGetPushMessages: vi.fn(),
}))

vi.mock('@/api/modules/console', () => ({
  consoleApi: { getPushMessages: mockGetPushMessages },
}))

const makeMessages = (ids: string[]) => ({
  messages: ids.map((id) => ({ id, text: `Message ${id}` })),
})

// ---------------------------------------------------------------------------
// Basic render tests (no fake timers needed, findBy* works fine)
// ---------------------------------------------------------------------------
describe('ConsoleCronBubble - basic rendering', () => {
  afterEach(() => vi.clearAllMocks())

  it('renders nothing when there are no messages', async () => {
    mockGetPushMessages.mockResolvedValue({ messages: [] })
    renderWithProviders(<ConsoleCronBubble />)
    // wait for the first poll to complete
    await act(async () => {})
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
  })

  it('renders bubble when messages are present', async () => {
    mockGetPushMessages.mockResolvedValue(makeMessages(['msg-1']))
    renderWithProviders(<ConsoleCronBubble />)
    expect(await screen.findByText('Message msg-1')).toBeInTheDocument()
  })

  it('renders each message separately', async () => {
    mockGetPushMessages.mockResolvedValue(makeMessages(['a', 'b']))
    renderWithProviders(<ConsoleCronBubble />)
    expect(await screen.findByText('Message a')).toBeInTheDocument()
    expect(await screen.findByText('Message b')).toBeInTheDocument()
  })

  it('clicking the close button removes the corresponding bubble', async () => {
    const user = userEvent.setup()
    mockGetPushMessages.mockResolvedValue(makeMessages(['x']))
    renderWithProviders(<ConsoleCronBubble />)

    const closeBtn = await screen.findByRole('button', { name: 'Close' })
    await user.click(closeBtn)

    expect(screen.queryByText('Message x')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Polling behavior tests (fake timers needed to control setInterval)
// ---------------------------------------------------------------------------
describe('ConsoleCronBubble - polling behavior', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockGetPushMessages.mockResolvedValue({ messages: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('duplicate messages are not rendered (seen ids deduplication)', async () => {
    mockGetPushMessages.mockResolvedValue(makeMessages(['dup-1']))
    renderWithProviders(<ConsoleCronBubble />)

    // first tick
    await act(async () => { await Promise.resolve() })
    // advance timer to trigger second poll
    await act(async () => {
      vi.advanceTimersByTime(2500)
      await Promise.resolve()
    })

    expect(screen.queryAllByText('Message dup-1').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Message dup-1').length).toBeLessThanOrEqual(1)
  })

  it('shows at most 4 bubbles when exceeding MAX_VISIBLE_BUBBLES(4)', async () => {
    mockGetPushMessages
      .mockResolvedValueOnce(makeMessages(['1', '2']))
      .mockResolvedValueOnce(makeMessages(['3', '4']))
      .mockResolvedValueOnce(makeMessages(['5', '6']))
      .mockResolvedValueOnce(makeMessages(['7', '8']))

    renderWithProviders(<ConsoleCronBubble />)

    for (let i = 0; i < 4; i++) {
      await act(async () => {
        vi.advanceTimersByTime(2500)
        await Promise.resolve()
      })
    }

    expect(screen.queryAllByRole('button', { name: 'Close' }).length).toBeLessThanOrEqual(4)
  })
})
