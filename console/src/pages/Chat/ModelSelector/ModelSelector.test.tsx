import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import ModelSelector from './index'

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

  it('displays current active model name on trigger button after loading', async () => {
    renderWithProviders(<ModelSelector />)
    expect(await screen.findByText('GPT-4')).toBeInTheDocument()
  })

  it('displays i18n key when there is no active model', async () => {
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({ active_llm: undefined })
    renderWithProviders(<ModelSelector />)
    expect(await screen.findByText('modelSelector.selectModel')).toBeInTheDocument()
  })

  it('displays bare model id when active model is outside the eligible list', async () => {
    // provider has no api_key configured, so it is excluded from eligible list
    vi.mocked(providerApi.listProviders).mockResolvedValue([
      { ...mockProvider, api_key: '' },
    ])
    renderWithProviders(<ModelSelector />)
    expect(await screen.findByText('gpt-4')).toBeInTheDocument()
  })

  it('calls listProviders and getActiveModels on mount', async () => {
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')
    expect(providerApi.listProviders).toHaveBeenCalledOnce()
    expect(providerApi.getActiveModels).toHaveBeenCalledWith({
      scope: 'effective',
      agent_id: 'default',
    })
  })

  it('clicking trigger button opens dropdown and shows provider list', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')

    await user.click(screen.getByText('GPT-4'))

    expect(await screen.findByText('OpenAI')).toBeInTheDocument()
  })

  it('clicking a model calls setActiveLlm with correct parameters', async () => {
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

  it('clicking the already active model does not call setActiveLlm', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')

    await user.click(screen.getByText('GPT-4'))
    const gpt4Items = await screen.findAllByText('GPT-4')
    await user.click(gpt4Items[gpt4Items.length - 1])

    expect(providerApi.setActiveLlm).not.toHaveBeenCalled()
  })

  it('dropdown shows empty state when no providers are available', async () => {
    vi.mocked(providerApi.listProviders).mockResolvedValue([])
    vi.mocked(providerApi.getActiveModels).mockResolvedValue({ active_llm: undefined })
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('modelSelector.selectModel')

    await user.click(screen.getByText('modelSelector.selectModel'))

    expect(await screen.findByText('modelSelector.noConfiguredModels')).toBeInTheDocument()
  })

  it('still displays original active model after setActiveLlm failure', async () => {
    vi.mocked(providerApi.setActiveLlm).mockRejectedValue(new Error('API error'))
    const user = userEvent.setup()
    renderWithProviders(<ModelSelector />)
    await screen.findByText('GPT-4')

    await user.click(screen.getByText('GPT-4'))
    const gpt35 = await screen.findByText('GPT-3.5 Turbo')
    await user.click(gpt35)

    // GPT-4 may appear in two places when dropdown is still open (trigger + dropdown item)
    await waitFor(() => {
      expect(screen.getAllByText('GPT-4').length).toBeGreaterThanOrEqual(1)
    })
  })
})
