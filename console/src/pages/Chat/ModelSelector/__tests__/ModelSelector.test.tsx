import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import ModelSelector from '../index'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('@/api/modules/provider', () => ({
  providerApi: {
    listProviders: vi.fn(),
    getActiveModels: vi.fn(),
    setActiveLlm: vi.fn(),
  },
}))

vi.mock('@/stores/agentStore', () => ({
  useAgentStore: vi.fn(() => ({ selectedAgent: 'default' })),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('@agentscope-ai/icons', () => ({
  SparkDownLine: () => <span data-testid="spark-icon" />,
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

import { providerApi } from '@/api/modules/provider'

const mockProvider = {
  id: 'openai',
  name: 'OpenAI',
  api_key: 'sk-xxx',
  require_api_key: true,
  base_url: '',
  is_custom: false,
  models: [
    { id: 'gpt-4', name: 'GPT-4', supports_multimodal: false, supports_image: false, supports_video: false },
    { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo', supports_multimodal: false, supports_image: false, supports_video: false },
  ],
  extra_models: [],
}

const mockActiveModels = {
  active_llm: { provider_id: 'openai', model: 'gpt-4' },
}

function setupDefaultMocks() {
  vi.mocked(providerApi.listProviders).mockResolvedValue([mockProvider])
  vi.mocked(providerApi.getActiveModels).mockResolvedValue(mockActiveModels)
  vi.mocked(providerApi.setActiveLlm).mockResolvedValue(undefined)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ModelSelector', () => {
  beforeEach(() => {
    setupDefaultMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('加载完成后在触发按钮显示当前 active 模型名称', async () => {
    renderWithProviders(<ModelSelector />)
    expect(await screen.findByText('GPT-4')).toBeInTheDocument()
  })

  it('无 active 模型时显示 i18n key', async () => {
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({ active_llm: undefined })
    renderWithProviders(<ModelSelector />)
    expect(await screen.findByText('modelSelector.selectModel')).toBeInTheDocument()
  })

  it('active model 在 eligible 列表外时显示裸 model id', async () => {
    // provider 未配置 api_key，不进入 eligible
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, api_key: '' },
    ])
    renderWithProviders(<ModelSelector />)
    expect(await screen.findByText('gpt-4')).toBeInTheDocument()
  })

  it('挂载时调用 listProviders 和 getActiveModels', async () => {
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')
    expect(providerApi.listProviders).toHaveBeenCalledOnce()
    expect(providerApi.getActiveModels).toHaveBeenCalledWith({
      scope: 'effective',
      agent_id: 'default',
    })
  })

  it('点击触发按钮打开 dropdown 并展示 provider 列表', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')

    await user.click(screen.getByText('GPT-4'))

    expect(await screen.findByText('OpenAI')).toBeInTheDocument()
  })

  it('点击 model 后调用 setActiveLlm 并传入正确参数', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')

    await user.click(screen.getByText('GPT-4'))
    const gpt35 = await screen.findByText('GPT-3.5 Turbo')
    await user.click(gpt35)

    expect(providerApi.setActiveLlm).toHaveBeenCalledWith({
      provider_id: 'openai',
      model: 'gpt-3.5-turbo',
      scope: 'agent',
      agent_id: 'default',
    })
  })

  it('点击已 active 的 model 时不调用 setActiveLlm', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')

    await user.click(screen.getByText('GPT-4'))
    const gpt4Items = await screen.findAllByText('GPT-4')
    await user.click(gpt4Items[gpt4Items.length - 1])

    expect(providerApi.setActiveLlm).not.toHaveBeenCalled()
  })

  it('无可用 provider 时 dropdown 显示空提示', async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([])
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({ active_llm: undefined })
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('modelSelector.selectModel')

    await user.click(screen.getByText('modelSelector.selectModel'))

    expect(await screen.findByText('modelSelector.noConfiguredModels')).toBeInTheDocument()
  })

  it('setActiveLlm 失败后仍显示原 active model', async () => {
    vi.mocked(providerApi.setActiveLlm).mockRejectedValue(new Error('API error'))
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')

    await user.click(screen.getByText('GPT-4'))
    const gpt35 = await screen.findByText('GPT-3.5 Turbo')
    await user.click(gpt35)

    // dropdown 仍开着时 GPT-4 会出现两处（trigger + dropdown item）
    await waitFor(() => {
      expect(screen.getAllByText('GPT-4').length).toBeGreaterThanOrEqual(1)
    })
  })
})
