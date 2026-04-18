import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { authApi } from '../auth'

// auth.ts 直接用 fetch，不走 request 封装，需要 mock 全局 fetch
vi.mock('../config', () => ({
  getApiUrl: (path: string) => `/api${path}`,
}))

function mockFetch(status: number, body: unknown) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Bad Request',
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body)),
  } as unknown as Response)
}

describe('authApi.login', () => {
  afterEach(() => vi.clearAllMocks())

  it('成功登录返回 token 和 username', async () => {
    mockFetch(200, { token: 'tok-123', username: 'alice' })
    const result = await authApi.login('alice', 'pass')
    expect(result).toEqual({ token: 'tok-123', username: 'alice' })
  })

  it('发送 POST 到 /api/auth/login', async () => {
    mockFetch(200, { token: 'tok', username: 'alice' })
    await authApi.login('alice', 'pass')
    expect(fetch).toHaveBeenCalledWith(
      '/api/auth/login',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('请求体包含 username 和 password', async () => {
    mockFetch(200, { token: 'tok', username: 'alice' })
    await authApi.login('alice', 'secret')
    const body = JSON.parse((fetch as any).mock.calls[0][1].body)
    expect(body).toEqual({ username: 'alice', password: 'secret' })
  })

  it('登录失败抛出含 detail 的错误', async () => {
    mockFetch(401, { detail: '用户名或密码错误' })
    await expect(authApi.login('alice', 'wrong')).rejects.toThrow('用户名或密码错误')
  })

  it('响应无 detail 时抛出默认错误', async () => {
    mockFetch(401, {})
    await expect(authApi.login('alice', 'wrong')).rejects.toThrow('Login failed')
  })
})

describe('authApi.register', () => {
  afterEach(() => vi.clearAllMocks())

  it('成功注册返回 token 和 username', async () => {
    mockFetch(200, { token: 'tok-new', username: 'bob' })
    const result = await authApi.register('bob', 'pass123')
    expect(result.token).toBe('tok-new')
  })

  it('发送 POST 到 /api/auth/register', async () => {
    mockFetch(200, { token: 't', username: 'bob' })
    await authApi.register('bob', 'pass')
    expect(fetch).toHaveBeenCalledWith('/api/auth/register', expect.anything())
  })

  it('注册失败抛出 detail 错误信息', async () => {
    mockFetch(409, { detail: '用户名已存在' })
    await expect(authApi.register('bob', 'pass')).rejects.toThrow('用户名已存在')
  })

  it('响应无 detail 时抛出 Registration failed', async () => {
    mockFetch(500, {})
    await expect(authApi.register('bob', 'pass')).rejects.toThrow('Registration failed')
  })
})

describe('authApi.getStatus', () => {
  afterEach(() => vi.clearAllMocks())

  it('返回 enabled 和 has_users 字段', async () => {
    mockFetch(200, { enabled: true, has_users: false })
    const result = await authApi.getStatus()
    expect(result).toEqual({ enabled: true, has_users: false })
  })

  it('请求失败时抛出错误', async () => {
    mockFetch(500, {})
    // getStatus 检查 !res.ok 但 json() 不会报错，需要 ok 为 false
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    } as unknown as Response)
    await expect(authApi.getStatus()).rejects.toThrow('Failed to check auth status')
  })
})

describe('authApi.updateProfile', () => {
  beforeEach(() => {
    localStorage.clear()
  })
  afterEach(() => vi.clearAllMocks())

  it('发送 POST 到 /api/auth/update-profile', async () => {
    mockFetch(200, { token: 't', username: 'alice' })
    await authApi.updateProfile('oldpass', 'newname')
    expect(fetch).toHaveBeenCalledWith('/api/auth/update-profile', expect.anything())
  })

  it('请求体包含当前密码和新用户名', async () => {
    mockFetch(200, { token: 't', username: 'newname' })
    await authApi.updateProfile('oldpass', 'newname')
    const body = JSON.parse((fetch as any).mock.calls[0][1].body)
    expect(body.current_password).toBe('oldpass')
    expect(body.new_username).toBe('newname')
    expect(body.new_password).toBeNull()
  })

  it('从 localStorage 读取 token 注入 Authorization header', async () => {
    localStorage.setItem('copaw_auth_token', 'my-token')
    mockFetch(200, { token: 't', username: 'alice' })
    await authApi.updateProfile('oldpass')
    const headers = (fetch as any).mock.calls[0][1].headers
    expect(headers.Authorization).toBe('Bearer my-token')
  })

  it('更新失败时抛出 detail 错误', async () => {
    mockFetch(400, { detail: '密码错误' })
    await expect(authApi.updateProfile('wrong')).rejects.toThrow('密码错误')
  })
})
