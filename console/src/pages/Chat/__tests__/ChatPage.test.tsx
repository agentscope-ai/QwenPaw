/**
 * Chat/index.tsx 行为测试
 *
 * 策略（参考 openclaw chat.test.ts 模式）：
 * - 将 AgentScopeRuntimeWebUI mock 为可捕获 options prop 的 spy 组件
 * - 直接调用 options.api.fetch / options.sender.attachments.customRequest
 *   等回调，测试 ChatPage 自身逻辑，不依赖真实 WebSocket 运行时
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import ChatPage from '../index'

// ---------------------------------------------------------------------------
// 捕获 AgentScopeRuntimeWebUI options
// ---------------------------------------------------------------------------
let capturedOptions: any = null

const {
  mockListProviders,
  mockGetActiveModels,
  mockUploadFile,
  mockFilePreviewUrl,
  mockGetApiUrl,
  mockSelectedAgent,
  mockSetSelectedAgent,
} = vi.hoisted(() => ({
  mockListProviders: vi.fn(),
  mockGetActiveModels: vi.fn(),
  mockUploadFile: vi.fn(),
  mockFilePreviewUrl: vi.fn((f: string) => `/preview/${f}`),
  mockGetApiUrl: vi.fn((p: string) => `/api${p}`),
  mockSelectedAgent: vi.fn(() => 'default'),
  mockSetSelectedAgent: vi.fn(),
}))

vi.mock('@agentscope-ai/chat', () => ({
  // 渲染 rightHeader，让子组件出现在 DOM 里
  AgentScopeRuntimeWebUI: vi.fn((props: any) => {
    capturedOptions = props.options
    return (
      <div data-testid="chat-ui">
        {props.options?.theme?.rightHeader}
      </div>
    )
  }),
  useChatAnywhereInput: vi.fn(() => ({
    setLoading: vi.fn(),
    getLoading: vi.fn(),
  })),
}))

vi.mock('@agentscope-ai/design', () => ({
  IconButton: ({ onClick, icon, disabled }: any) => (
    <button onClick={onClick} disabled={disabled}>{icon}</button>
  ),
}))

vi.mock('@agentscope-ai/icons', () => ({
  SparkCopyLine: () => <span data-testid="icon-copy" />,
  SparkAttachmentLine: () => <span data-testid="icon-attach" />,
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, opts?: any) => opts ? `${k}:${JSON.stringify(opts)}` : k }),
}))

vi.mock('@/api/modules/provider', () => ({
  providerApi: { listProviders: mockListProviders, getActiveModels: mockGetActiveModels },
}))

vi.mock('@/api/modules/chat', () => ({
  chatApi: { uploadFile: mockUploadFile, filePreviewUrl: mockFilePreviewUrl, stopChat: vi.fn() },
}))

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<typeof import('antd')>()
  return {
    ...actual,
    // Modal：open=false 时不渲染，避免 CSS 动画导致内容留在 DOM
    Modal: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
      open ? <div data-testid="modal">{children}</div> : null,
  }
})
vi.mock('@/api/config', () => ({
  getApiUrl: mockGetApiUrl,
  getApiToken: vi.fn(() => ''),
}))

vi.mock('@/stores/agentStore', () => ({
  useAgentStore: vi.fn(() => ({
    selectedAgent: mockSelectedAgent(),
    setSelectedAgent: mockSetSelectedAgent,
  })),
}))

vi.mock('@/contexts/ThemeContext', () => ({
  useTheme: vi.fn(() => ({ isDark: false })),
}))

vi.mock('../sessionApi', () => ({
  default: {
    onSessionIdResolved: null,
    onSessionRemoved: null,
    onSessionSelected: null,
    onSessionCreated: null,
    getRealIdForSession: vi.fn(() => null),
    setLastUserMessage: vi.fn(),
  },
}))

vi.mock('../OptionsPanel/defaultConfig', () => ({
  default: { theme: { leftHeader: {} }, api: {} },
  getDefaultConfig: vi.fn(() => ({
    theme: { leftHeader: {} },
    welcome: {},
    sender: {},
  })),
}))

vi.mock('../ModelSelector', () => ({
  default: () => <div data-testid="model-selector" />,
}))

vi.mock('../components/ChatActionGroup', () => ({
  default: () => <div data-testid="action-group" />,
}))

vi.mock('../components/ChatHeaderTitle', () => ({
  default: () => <div data-testid="header-title" />,
}))

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
const mockActiveModel = {
  active_llm: { provider_id: 'openai', model: 'gpt-4' },
}
const mockProviders = [
  {
    id: 'openai', name: 'OpenAI',
    models: [{ id: 'gpt-4', name: 'GPT-4', supports_multimodal: true, supports_image: true, supports_video: false }],
    extra_models: [],
  },
]

// ---------------------------------------------------------------------------
// tests
// ---------------------------------------------------------------------------
describe('ChatPage', () => {
  beforeEach(() => {
    capturedOptions = null
    mockListProviders.mockResolvedValue(mockProviders)
    mockGetActiveModels.mockResolvedValue(mockActiveModel)
    mockUploadFile.mockResolvedValue({ url: 'uploaded.png', file_name: 'uploaded.png' })
  })

  afterEach(() => vi.clearAllMocks())

  // ── 基础渲染 ─────────────────────────────────────────────────────────────

  it('渲染 AgentScopeRuntimeWebUI', async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    expect(await screen.findByTestId('chat-ui')).toBeInTheDocument()
  })

  it('渲染子组件 ModelSelector / ChatActionGroup / ChatHeaderTitle', async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')
    expect(screen.getByTestId('model-selector')).toBeInTheDocument()
    expect(screen.getByTestId('action-group')).toBeInTheDocument()
    expect(screen.getByTestId('header-title')).toBeInTheDocument()
  })

  // ── customFetch：model 未配置 → 弹 modal ─────────────────────────────────

  it('未配置 model 时 customFetch 返回 400 并显示 modal', async () => {
    mockGetActiveModels.mockResolvedValue({ active_llm: undefined })
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')

    // 直接调用 capturedOptions.api.fetch（openclaw 模式）
    const response = await capturedOptions.api.fetch({ input: [], signal: undefined })
    expect(response.status).toBe(400)
    expect(await screen.findByText('modelConfig.promptTitle')).toBeInTheDocument()
  })

  it('provider API 异常时也显示 model 配置 modal', async () => {
    mockGetActiveModels.mockRejectedValue(new Error('network'))
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')

    const response = await capturedOptions.api.fetch({ input: [], signal: undefined })
    expect(response.status).toBe(400)
    expect(await screen.findByText('modelConfig.promptTitle')).toBeInTheDocument()
  })

  // ── modal 交互 ────────────────────────────────────────────────────────────

  it('点击 Skip 按钮关闭 modal', async () => {
    mockGetActiveModels.mockResolvedValue({ active_llm: undefined })
    const user = userEvent.setup()
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')

    await capturedOptions.api.fetch({ input: [], signal: undefined })
    await screen.findByText('modelConfig.promptTitle')

    await user.click(screen.getByText('modelConfig.skipButton'))
    // antd Modal 有动画，等待 DOM 移除
    await waitFor(() =>
      expect(screen.queryByText('modelConfig.skipButton')).not.toBeInTheDocument(),
      { timeout: 3000 },
    )
  })

  // ── customFetch：正常发送 ────────────────────────────────────────────────

  it('model 已配置时 customFetch 调用 /api/console/chat', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 } as Response)
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')

    await capturedOptions.api.fetch({
      input: [{ role: 'user', content: 'hello' }],
      signal: undefined,
    })

    expect(fetch).toHaveBeenCalledWith('/api/console/chat', expect.objectContaining({ method: 'POST' }))
  })

  // ── handleFileUpload ──────────────────────────────────────────────────────

  it('文件超过 10MB 时调用 onError 并不上传', async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')

    const bigFile = new File([new ArrayBuffer(11 * 1024 * 1024)], 'big.bin', { type: 'application/octet-stream' })
    const onError = vi.fn()
    const onSuccess = vi.fn()

    await capturedOptions.sender.attachments.customRequest({ file: bigFile, onSuccess, onError })

    expect(onError).toHaveBeenCalledOnce()
    expect(mockUploadFile).not.toHaveBeenCalled()
  })

  it('文件在限制内时上传成功并调用 onSuccess', async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')

    const smallFile = new File(['content'], 'img.png', { type: 'image/png' })
    const onSuccess = vi.fn()
    const onError = vi.fn()

    await capturedOptions.sender.attachments.customRequest({
      file: smallFile, onSuccess, onError, onProgress: vi.fn(),
    })

    expect(mockUploadFile).toHaveBeenCalledWith(smallFile)
    expect(onSuccess).toHaveBeenCalledWith({ url: '/preview/uploaded.png' })
    expect(onError).not.toHaveBeenCalled()
  })

  // ── multimodal caps ───────────────────────────────────────────────────────

  it('挂载时调用 providerApi 获取 multimodal 能力', async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')
    await waitFor(() => expect(mockGetActiveModels).toHaveBeenCalled())
    expect(mockListProviders).toHaveBeenCalled()
  })

  it('model-switched 事件触发重新获取 multimodal 能力', async () => {
    renderWithProviders(<ChatPage />, { initialEntries: ['/chat'] })
    await screen.findByTestId('chat-ui')
    // 等 mount 时的初始调用稳定
    await waitFor(() => expect(mockGetActiveModels).toHaveBeenCalled())
    const callsBefore = mockGetActiveModels.mock.calls.length

    act(() => { window.dispatchEvent(new CustomEvent('model-switched')) })

    await waitFor(() =>
      expect(mockGetActiveModels.mock.calls.length).toBeGreaterThan(callsBefore),
    )
  })
})
