import { describe, it, expect } from 'vitest'
import { getAgentDisplayName } from '../agentDisplayName'
import { stripFrontmatter } from '../markdown'

// ---------------------------------------------------------------------------
// getAgentDisplayName
// ---------------------------------------------------------------------------

const t = (key: string) => key  // 测试用 t 函数：返回 key 本身

describe('getAgentDisplayName', () => {
  it('id 为 default 时返回 i18n key', () => {
    expect(getAgentDisplayName({ id: 'default', name: 'anything' }, t as any)).toBe(
      'agent.defaultDisplayName',
    )
  })

  it('非 default id 优先返回 name', () => {
    expect(getAgentDisplayName({ id: 'agent-1', name: 'My Agent' }, t as any)).toBe('My Agent')
  })

  it('name 为空时 fallback 到 id', () => {
    expect(getAgentDisplayName({ id: 'agent-1', name: '' }, t as any)).toBe('agent-1')
  })

  it('name 为 undefined 时 fallback 到 id', () => {
    expect(
      getAgentDisplayName({ id: 'agent-1', name: undefined as any }, t as any),
    ).toBe('agent-1')
  })
})

// ---------------------------------------------------------------------------
// stripFrontmatter
// ---------------------------------------------------------------------------

describe('stripFrontmatter', () => {
  it('移除标准 YAML frontmatter', () => {
    const input = '---\ntitle: Test\ndate: 2024-01-01\n---\n# Hello'
    expect(stripFrontmatter(input)).toBe('# Hello')
  })

  it('无 frontmatter 时原样返回', () => {
    const input = '# Hello\nsome content'
    expect(stripFrontmatter(input)).toBe(input)
  })

  it('空字符串返回空字符串', () => {
    expect(stripFrontmatter('')).toBe('')
  })

  it('保留 frontmatter 之后的全部内容', () => {
    const input = '---\nkey: value\n---\nline1\nline2\n\nline3'
    expect(stripFrontmatter(input)).toBe('line1\nline2\n\nline3')
  })

  it('只有 frontmatter 无正文时返回空', () => {
    const input = '---\ntitle: Only\n---\n'
    expect(stripFrontmatter(input)).toBe('')
  })

  it('Windows 换行符 \\r\\n 也能处理', () => {
    const input = '---\r\ntitle: Test\r\n---\r\n# Hello'
    expect(stripFrontmatter(input)).toBe('# Hello')
  })
})
