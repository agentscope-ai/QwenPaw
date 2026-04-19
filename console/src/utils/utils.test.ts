import { describe, it, expect } from 'vitest'
import { getAgentDisplayName } from './agentDisplayName'
import { stripFrontmatter } from './markdown'

// ---------------------------------------------------------------------------
// getAgentDisplayName
// ---------------------------------------------------------------------------

const t = (key: string) => key  // test t function: returns the key as-is

describe('getAgentDisplayName', () => {
  it('returns i18n key when id is "default"', () => {
    expect(getAgentDisplayName({ id: 'default', name: 'anything' }, t as any)).toBe(
      'agent.defaultDisplayName',
    )
  })

  it('returns name when id is not "default"', () => {
    expect(getAgentDisplayName({ id: 'agent-1', name: 'My Agent' }, t as any)).toBe('My Agent')
  })

  it('falls back to id when name is empty', () => {
    expect(getAgentDisplayName({ id: 'agent-1', name: '' }, t as any)).toBe('agent-1')
  })

  it('falls back to id when name is undefined', () => {
    expect(
      getAgentDisplayName({ id: 'agent-1', name: undefined as any }, t as any),
    ).toBe('agent-1')
  })
})

// ---------------------------------------------------------------------------
// stripFrontmatter
// ---------------------------------------------------------------------------

describe('stripFrontmatter', () => {
  it('removes standard YAML frontmatter', () => {
    const input = '---\ntitle: Test\ndate: 2024-01-01\n---\n# Hello'
    expect(stripFrontmatter(input)).toBe('# Hello')
  })

  it('returns input unchanged when no frontmatter', () => {
    const input = '# Hello\nsome content'
    expect(stripFrontmatter(input)).toBe(input)
  })

  it('returns empty string for empty input', () => {
    expect(stripFrontmatter('')).toBe('')
  })

  it('preserves all content after frontmatter', () => {
    const input = '---\nkey: value\n---\nline1\nline2\n\nline3'
    expect(stripFrontmatter(input)).toBe('line1\nline2\n\nline3')
  })

  it('returns empty string when only frontmatter with no body', () => {
    const input = '---\ntitle: Only\n---\n'
    expect(stripFrontmatter(input)).toBe('')
  })

  it('handles Windows line endings \\r\\n', () => {
    const input = '---\r\ntitle: Test\r\n---\r\n# Hello'
    expect(stripFrontmatter(input)).toBe('# Hello')
  })
})
