import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { providerApi } from '../provider'

vi.mock('@/api/request', () => ({
  request: vi.fn(),
}))

import { request } from '@/api/request'

describe('providerApi', () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('listProviders 调用 /models', async () => {
    await providerApi.listProviders()
    expect(request).toHaveBeenCalledWith('/models')
  })

  it('getActiveModels 无参数时调用 /models/active', async () => {
    await providerApi.getActiveModels()
    expect(request).toHaveBeenCalledWith('/models/active')
  })

  it('getActiveModels 只有 scope 时构建正确 query', async () => {
    await providerApi.getActiveModels({ scope: 'global' })
    expect(request).toHaveBeenCalledWith('/models/active?scope=global')
  })

  it('getActiveModels 只有 agent_id 时构建正确 query', async () => {
    await providerApi.getActiveModels({ agent_id: 'agent-1' })
    expect(request).toHaveBeenCalledWith('/models/active?agent_id=agent-1')
  })

  it('getActiveModels scope + agent_id 都有时构建正确 query', async () => {
    await providerApi.getActiveModels({ scope: 'effective', agent_id: 'agent-1' })
    expect(request).toHaveBeenCalledWith(
      '/models/active?scope=effective&agent_id=agent-1',
    )
  })

  it('setActiveLlm 发送 PUT 请求', async () => {
    const body = { provider_id: 'openai', model: 'gpt-4', scope: 'agent' as const }
    await providerApi.setActiveLlm(body)
    expect(request).toHaveBeenCalledWith('/models/active', {
      method: 'PUT',
      body: JSON.stringify(body),
    })
  })

  it('configureProvider 编码 providerId 并发送 PUT', async () => {
    await providerApi.configureProvider('open/ai', { api_key: 'sk-xxx' })
    expect(request).toHaveBeenCalledWith(
      '/models/open%2Fai/config',
      expect.objectContaining({ method: 'PUT' }),
    )
  })

  it('addModel 发送 POST 到正确路径', async () => {
    await providerApi.addModel('openai', { id: 'gpt-5', name: 'GPT-5' })
    expect(request).toHaveBeenCalledWith(
      '/models/openai/models',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('removeModel 发送 DELETE 并编码两个 id', async () => {
    await providerApi.removeModel('open/ai', 'gpt-4')
    expect(request).toHaveBeenCalledWith(
      '/models/open%2Fai/models/gpt-4',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })
})
