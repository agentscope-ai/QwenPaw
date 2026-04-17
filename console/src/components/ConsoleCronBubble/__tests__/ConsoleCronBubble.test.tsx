import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import ConsoleCronBubble from '../index'

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
// 基础渲染测试（不需要 fake timers，findBy* 能正常工作）
// ---------------------------------------------------------------------------
describe('ConsoleCronBubble - 基础渲染', () => {
  afterEach(() => vi.clearAllMocks())

  it('无消息时不渲染任何内容', async () => {
    mockGetPushMessages.mockResolvedValue({ messages: [] })
    renderWithProviders(<ConsoleCronBubble />)
    // 等首次 poll 完成
    await act(async () => {})
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
  })

  it('有消息时渲染 bubble', async () => {
    mockGetPushMessages.mockResolvedValue(makeMessages(['msg-1']))
    renderWithProviders(<ConsoleCronBubble />)
    expect(await screen.findByText('Message msg-1')).toBeInTheDocument()
  })

  it('多条消息各自渲染', async () => {
    mockGetPushMessages.mockResolvedValue(makeMessages(['a', 'b']))
    renderWithProviders(<ConsoleCronBubble />)
    expect(await screen.findByText('Message a')).toBeInTheDocument()
    expect(await screen.findByText('Message b')).toBeInTheDocument()
  })

  it('点击关闭按钮移除对应 bubble', async () => {
    const user = userEvent.setup()
    mockGetPushMessages.mockResolvedValue(makeMessages(['x']))
    renderWithProviders(<ConsoleCronBubble />)

    const closeBtn = await screen.findByRole('button', { name: 'Close' })
    await user.click(closeBtn)

    expect(screen.queryByText('Message x')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 轮询行为测试（需要 fake timers 控制 setInterval）
// ---------------------------------------------------------------------------
describe('ConsoleCronBubble - 轮询行为', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockGetPushMessages.mockResolvedValue({ messages: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('同一消息不重复渲染（seen ids 去重）', async () => {
    mockGetPushMessages.mockResolvedValue(makeMessages(['dup-1']))
    renderWithProviders(<ConsoleCronBubble />)

    // 首次 tick
    await act(async () => { await Promise.resolve() })
    // 推进轮询间隔，触发第二次 poll
    await act(async () => {
      vi.advanceTimersByTime(2500)
      await Promise.resolve()
    })

    expect(screen.queryAllByText('Message dup-1').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Message dup-1').length).toBeLessThanOrEqual(1)
  })

  it('超过 MAX_VISIBLE_BUBBLES(4) 时最多显示 4 条', async () => {
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
