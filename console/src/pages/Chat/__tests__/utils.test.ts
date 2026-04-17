import { describe, it, expect, vi } from 'vitest'
import {
  extractCopyableText,
  extractUserMessageText,
  buildModelError,
  toStoredName,
  normalizeContentUrls,
  toDisplayUrl,
} from '../utils'
import type { CopyableResponse } from '../utils'

// toDisplayUrl 依赖 chatApi.filePreviewUrl，需要 mock
vi.mock('@/api/modules/chat', () => ({
  chatApi: {
    filePreviewUrl: vi.fn((p: string) => `http://localhost:8000${p}`),
  },
}))

// ---------------------------------------------------------------------------
// extractCopyableText
// ---------------------------------------------------------------------------
describe('extractCopyableText', () => {
  it('提取 assistant 角色的字符串 content', () => {
    const response: CopyableResponse = {
      output: [
        { role: 'user', content: '你好' },
        { role: 'assistant', content: '你好，有什么可以帮你？' },
      ],
    }
    expect(extractCopyableText(response)).toBe('你好，有什么可以帮你？')
  })

  it('提取结构化 content 数组中的 text', () => {
    const response: CopyableResponse = {
      output: [
        {
          role: 'assistant',
          content: [
            { type: 'text', text: '第一段' },
            { type: 'text', text: '第二段' },
          ],
        },
      ],
    }
    expect(extractCopyableText(response)).toBe('第一段\n\n第二段')
  })

  it('提取 refusal 类型内容', () => {
    const response: CopyableResponse = {
      output: [
        {
          role: 'assistant',
          content: [{ type: 'refusal', refusal: '无法回答此问题' }],
        },
      ],
    }
    expect(extractCopyableText(response)).toBe('无法回答此问题')
  })

  it('无 assistant 消息时 fallback 到 JSON.stringify', () => {
    const response: CopyableResponse = {
      output: [{ role: 'user', content: '仅用户消息' }],
    }
    expect(extractCopyableText(response)).toBe(JSON.stringify(response))
  })

  it('output 为空时返回 JSON 序列化', () => {
    const response: CopyableResponse = { output: [] }
    expect(extractCopyableText(response)).toBe(JSON.stringify(response))
  })

  it('output 为 undefined 时不报错', () => {
    expect(() => extractCopyableText({})).not.toThrow()
  })

  it('多条 assistant 消息用双换行合并', () => {
    const response: CopyableResponse = {
      output: [
        { role: 'assistant', content: '第一句' },
        { role: 'assistant', content: '第二句' },
      ],
    }
    expect(extractCopyableText(response)).toBe('第一句\n\n第二句')
  })
})

// ---------------------------------------------------------------------------
// extractUserMessageText
// ---------------------------------------------------------------------------
describe('extractUserMessageText', () => {
  it('字符串 content 直接返回', () => {
    expect(extractUserMessageText({ content: '你好' })).toBe('你好')
  })

  it('数组 content 提取 text 类型并换行合并', () => {
    const msg = {
      content: [
        { type: 'text', text: '你好' },
        { type: 'image_url', image_url: 'http://...' },
        { type: 'text', text: '世界' },
      ],
    }
    expect(extractUserMessageText(msg)).toBe('你好\n世界')
  })

  it('非字符串非数组返回空字符串', () => {
    expect(extractUserMessageText({ content: null })).toBe('')
    expect(extractUserMessageText({ content: 123 })).toBe('')
  })
})

// ---------------------------------------------------------------------------
// buildModelError
// ---------------------------------------------------------------------------
describe('buildModelError', () => {
  it('返回 400 状态码', () => {
    const response = buildModelError()
    expect(response.status).toBe(400)
  })

  it('响应体包含 error 和 message 字段', async () => {
    const response = buildModelError()
    const body = await response.json()
    expect(body).toHaveProperty('error')
    expect(body).toHaveProperty('message')
  })

  it('Content-Type 为 application/json', () => {
    const response = buildModelError()
    expect(response.headers.get('Content-Type')).toBe('application/json')
  })
})

// ---------------------------------------------------------------------------
// toStoredName
// ---------------------------------------------------------------------------
describe('toStoredName', () => {
  test.each([
    [
      '提取 /files/preview/ 后的路径',
      'http://host/files/preview/uploads/img.png',
      '/uploads/img.png',
    ],
    [
      '去掉查询参数',
      'http://host/files/preview/img.png?token=abc',
      '/img.png',
    ],
    [
      '去掉 hash',
      'http://host/files/preview/img.png#section',
      '/img.png',
    ],
    [
      '无 marker 时原样返回',
      '/local/path/file.txt',
      '/local/path/file.txt',
    ],
    [
      'URL 编码路径正确解码',
      'http://host/files/preview/%E4%B8%AD%E6%96%87.txt',
      '/中文.txt',
    ],
  ])('%s', (_, input, expected) => {
    expect(toStoredName(input)).toBe(expected)
  })
})

// ---------------------------------------------------------------------------
// normalizeContentUrls
// ---------------------------------------------------------------------------
describe('normalizeContentUrls', () => {
  it('转换 image 类型的 image_url', () => {
    const part = { type: 'image', image_url: 'http://host/files/preview/img.png' }
    const result = normalizeContentUrls(part)
    expect(result.image_url).toBe('/img.png')
  })

  it('转换 file 类型的 file_url', () => {
    const part = { type: 'file', file_url: 'http://host/files/preview/doc.pdf' }
    const result = normalizeContentUrls(part)
    expect(result.file_url).toBe('/doc.pdf')
  })

  it('转换 audio 类型的 data', () => {
    const part = { type: 'audio', data: 'http://host/files/preview/audio.mp3' }
    const result = normalizeContentUrls(part)
    expect(result.data).toBe('/audio.mp3')
  })

  it('不影响 text 类型', () => {
    const part = { type: 'text', text: 'hello' }
    expect(normalizeContentUrls(part)).toEqual(part)
  })

  it('不修改原对象（shallow copy）', () => {
    const part = { type: 'image', image_url: 'http://host/files/preview/img.png' }
    normalizeContentUrls(part)
    expect(part.image_url).toBe('http://host/files/preview/img.png')
  })
})

// ---------------------------------------------------------------------------
// toDisplayUrl
// ---------------------------------------------------------------------------
describe('toDisplayUrl', () => {
  it('http URL 原样返回', () => {
    expect(toDisplayUrl('http://cdn.com/img.png')).toBe('http://cdn.com/img.png')
  })

  it('https URL 原样返回', () => {
    expect(toDisplayUrl('https://cdn.com/file')).toBe('https://cdn.com/file')
  })

  it('undefined 返回空字符串', () => {
    expect(toDisplayUrl(undefined)).toBe('')
  })

  it('空字符串返回空字符串', () => {
    expect(toDisplayUrl('')).toBe('')
  })

  it('相对路径调用 chatApi.filePreviewUrl', () => {
    expect(toDisplayUrl('/uploads/img.png')).toBe('http://localhost:8000/uploads/img.png')
  })

  it('file:// 协议去掉前缀后补全 URL', () => {
    expect(toDisplayUrl('file:///uploads/img.png')).toBe('http://localhost:8000/uploads/img.png')
  })
})
