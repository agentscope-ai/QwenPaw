import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { chatApi } from '../chat'

// chat.ts 混用 fetch（uploadFile）和 request 封装（其余），分别 mock
vi.mock('../../request', () => ({ request: vi.fn() }))
vi.mock('../../config', () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: vi.fn(() => ''),
}))
vi.mock('../../authHeaders', () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}))

import { request } from '../../request'
import { getApiToken } from '../../config'

// ---------------------------------------------------------------------------
// filePreviewUrl — 纯函数，最高 ROI
// ---------------------------------------------------------------------------
describe('chatApi.filePreviewUrl', () => {
  afterEach(() => vi.clearAllMocks())

  it('空字符串返回空字符串', () => {
    expect(chatApi.filePreviewUrl('')).toBe('')
  })

  it('http URL 原样返回', () => {
    expect(chatApi.filePreviewUrl('http://cdn.com/img.png')).toBe('http://cdn.com/img.png')
  })

  it('https URL 原样返回', () => {
    expect(chatApi.filePreviewUrl('https://cdn.com/img.png')).toBe('https://cdn.com/img.png')
  })

  it('相对路径拼接 /api/files/preview/', () => {
    const result = chatApi.filePreviewUrl('img.png')
    expect(result).toBe('/api/files/preview/img.png')
  })

  it('去掉路径开头多余的 /', () => {
    const result = chatApi.filePreviewUrl('/img.png')
    expect(result).toBe('/api/files/preview/img.png')
  })

  it('有 token 时追加 ?token= 参数', () => {
    vi.mocked(getApiToken).mockReturnValue('my-token')
    const result = chatApi.filePreviewUrl('img.png')
    expect(result).toContain('?token=my-token')
  })

  it('token 含特殊字符时做 URL 编码', () => {
    vi.mocked(getApiToken).mockReturnValue('tok en+1')
    const result = chatApi.filePreviewUrl('img.png')
    expect(result).toContain('token=tok%20en%2B1')
  })

  it('无 token 时不追加参数', () => {
    vi.mocked(getApiToken).mockReturnValue('')
    const result = chatApi.filePreviewUrl('img.png')
    expect(result).not.toContain('?token')
  })
})

// ---------------------------------------------------------------------------
// uploadFile — raw fetch，有错误处理逻辑
// ---------------------------------------------------------------------------
describe('chatApi.uploadFile', () => {
  afterEach(() => vi.clearAllMocks())

  it('上传成功返回 url 和 file_name', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ url: '/uploads/img.png', file_name: 'img.png' }),
    } as unknown as Response)

    const file = new File(['content'], 'img.png', { type: 'image/png' })
    const result = await chatApi.uploadFile(file)
    expect(result).toEqual({ url: '/uploads/img.png', file_name: 'img.png' })
  })

  it('发送 POST 到 /api/console/upload', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ url: '', file_name: '' }),
    } as unknown as Response)

    await chatApi.uploadFile(new File([''], 'f.txt'))
    expect(fetch).toHaveBeenCalledWith('/api/console/upload', expect.objectContaining({ method: 'POST' }))
  })

  it('上传失败抛出含状态码的错误', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      statusText: 'Payload Too Large',
      text: () => Promise.resolve('File too large'),
    } as unknown as Response)

    await expect(chatApi.uploadFile(new File([''], 'big.bin'))).rejects.toThrow(
      'Upload failed: 413 Payload Too Large - File too large',
    )
  })

  it('上传失败且无响应体时抛出不含 dash 的错误', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: () => Promise.resolve(''),
    } as unknown as Response)

    const err = await chatApi.uploadFile(new File([''], 'f.bin')).catch((e) => e)
    expect(err.message).toBe('Upload failed: 500 Internal Server Error')
  })
})

// ---------------------------------------------------------------------------
// listChats — query string 构建逻辑
// ---------------------------------------------------------------------------
describe('chatApi.listChats', () => {
  beforeEach(() => vi.mocked(request).mockResolvedValue([]))
  afterEach(() => vi.clearAllMocks())

  it('无参数时调用 /chats', async () => {
    await chatApi.listChats()
    expect(request).toHaveBeenCalledWith('/chats')
  })

  it('有 user_id 时构建 query string', async () => {
    await chatApi.listChats({ user_id: 'u1' })
    expect(request).toHaveBeenCalledWith('/chats?user_id=u1')
  })

  it('有 channel 时构建 query string', async () => {
    await chatApi.listChats({ channel: 'console' })
    expect(request).toHaveBeenCalledWith('/chats?channel=console')
  })

  it('两个参数同时存在时都出现在 query', async () => {
    await chatApi.listChats({ user_id: 'u1', channel: 'dingtalk' })
    expect(request).toHaveBeenCalledWith(expect.stringContaining('user_id=u1'))
    expect(request).toHaveBeenCalledWith(expect.stringContaining('channel=dingtalk'))
  })
})

// ---------------------------------------------------------------------------
// 其他方法 — 验证路径和 HTTP method
// ---------------------------------------------------------------------------
describe('chatApi CRUD', () => {
  beforeEach(() => vi.mocked(request).mockResolvedValue(undefined))
  afterEach(() => vi.clearAllMocks())

  it('getChat 编码 chatId 并发 GET', async () => {
    await chatApi.getChat('chat/1')
    expect(request).toHaveBeenCalledWith('/chats/chat%2F1')
  })

  it('updateChat 发 PUT 到正确路径', async () => {
    await chatApi.updateChat('chat-1', { name: 'New Name' })
    expect(request).toHaveBeenCalledWith(
      '/chats/chat-1',
      expect.objectContaining({ method: 'PUT' }),
    )
  })

  it('deleteChat 发 DELETE 到正确路径', async () => {
    await chatApi.deleteChat('chat-1')
    expect(request).toHaveBeenCalledWith(
      '/chats/chat-1',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('stopChat 编码 chatId 追加 query 参数', async () => {
    await chatApi.stopChat('chat/1')
    expect(request).toHaveBeenCalledWith(
      '/console/chat/stop?chat_id=chat%2F1',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('batchDeleteChats 发 POST 含 id 列表', async () => {
    await chatApi.batchDeleteChats(['id1', 'id2'])
    expect(request).toHaveBeenCalledWith(
      '/chats/batch-delete',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(['id1', 'id2']),
      }),
    )
  })
})
