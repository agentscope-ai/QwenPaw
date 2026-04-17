import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { request } from '../request'

// mock config so URL is predictable and token is empty by default
vi.mock('../config', () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: vi.fn(() => ''),
  clearAuthToken: vi.fn(),
}))

vi.mock('../authHeaders', () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}))

import { clearAuthToken } from '../config'
import { buildAuthHeaders } from '../authHeaders'

// Helper: create a mock Response
function mockFetch(status: number, body?: unknown, contentType = 'application/json') {
  const responseBody = body !== undefined
    ? typeof body === 'string' ? body : JSON.stringify(body)
    : ''

  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : status === 401 ? 'Unauthorized' : 'Error',
    headers: { get: () => contentType },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(responseBody),
  } as unknown as Response)
}

describe('request', () => {
  beforeEach(() => {
    vi.mocked(buildAuthHeaders).mockReturnValue({})
    Object.defineProperty(window, 'location', {
      value: { pathname: '/chat', href: '' },
      writable: true,
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  // ---------------------------------------------------------------------------
  // 正常请求
  // ---------------------------------------------------------------------------

  it('GET 请求不设置 Content-Type', async () => {
    mockFetch(200, { data: 'ok' })
    await request('/models')
    const headers: Headers = (fetch as any).mock.calls[0][1].headers
    expect(headers.has('Content-Type')).toBe(false)
  })

  it('POST 请求自动加 Content-Type: application/json', async () => {
    mockFetch(200, { data: 'ok' })
    await request('/models', { method: 'POST', body: '{}' })
    const headers: Headers = (fetch as any).mock.calls[0][1].headers
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('PUT 请求自动加 Content-Type', async () => {
    mockFetch(200, { status: 'ok' })
    await request('/models/active', { method: 'PUT', body: '{}' })
    const headers: Headers = (fetch as any).mock.calls[0][1].headers
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('调用者显式设置 Content-Type 时不被覆盖', async () => {
    mockFetch(200, { status: 'ok' })
    await request('/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const headers: Headers = (fetch as any).mock.calls[0][1].headers
    expect(headers.get('Content-Type')).toBe('multipart/form-data')
  })

  it('JSON 响应正确解析并返回', async () => {
    mockFetch(200, { id: 1, name: 'test' })
    const result = await request<{ id: number; name: string }>('/models')
    expect(result).toEqual({ id: 1, name: 'test' })
  })

  it('非 JSON Content-Type 返回文本', async () => {
    mockFetch(200, 'plain text response', 'text/plain')
    const result = await request('/health')
    expect(result).toBe('plain text response')
  })

  it('204 响应返回 undefined', async () => {
    mockFetch(204, undefined, '')
    const result = await request('/models/active')
    expect(result).toBeUndefined()
  })

  // ---------------------------------------------------------------------------
  // 错误处理
  // ---------------------------------------------------------------------------

  it('401 时调用 clearAuthToken 并跳转 /login', async () => {
    mockFetch(401)
    await expect(request('/models')).rejects.toThrow('Not authenticated')
    expect(clearAuthToken).toHaveBeenCalledOnce()
    expect(window.location.href).toBe('/login')
  })

  it('401 时已在 /login 页面不重复跳转', async () => {
    window.location.pathname = '/login'
    window.location.href = ''
    mockFetch(401)
    await expect(request('/models')).rejects.toThrow('Not authenticated')
    expect(window.location.href).toBe('')
  })

  it('非 401 错误抛出含状态码的错误', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      headers: { get: () => 'application/json' },
      text: () => Promise.resolve('server exploded'),
    } as unknown as Response)

    await expect(request('/models')).rejects.toThrow(
      'Request failed: 500 Internal Server Error - server exploded',
    )
  })

  it('有 token 时注入 Authorization header', async () => {
    vi.mocked(buildAuthHeaders).mockReturnValue({ Authorization: 'Bearer test-token' })
    mockFetch(200, {})
    await request('/models')
    const headers: Headers = (fetch as any).mock.calls[0][1].headers
    expect(headers.get('Authorization')).toBe('Bearer test-token')
  })

  it('请求 URL 由 getApiUrl 正确构建', async () => {
    mockFetch(200, {})
    await request('/models/active')
    expect(fetch).toHaveBeenCalledWith('/api/models/active', expect.any(Object))
  })
})
