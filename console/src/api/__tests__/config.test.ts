import { describe, it, expect, beforeEach } from 'vitest'
import { getApiUrl, getApiToken, setAuthToken, clearAuthToken } from '../config'

// VITE_API_BASE_URL / TOKEN are declared globals in config.ts — set via globalThis
const setViteBase = (v: string) => { (globalThis as any).VITE_API_BASE_URL = v }
const setToken    = (v: string) => { (globalThis as any).TOKEN = v }

describe('getApiUrl', () => {
  beforeEach(() => setViteBase(''))

  it('相对路径：空 base 时拼接 /api 前缀', () => {
    expect(getApiUrl('/models')).toBe('/api/models')
  })

  it('path 不以 / 开头时自动补 /', () => {
    expect(getApiUrl('models')).toBe('/api/models')
  })

  it('有 base URL 时正确拼接', () => {
    setViteBase('http://localhost:8088')
    expect(getApiUrl('/models')).toBe('http://localhost:8088/api/models')
  })

  it('嵌套路径正确拼接', () => {
    expect(getApiUrl('/models/openai/config')).toBe('/api/models/openai/config')
  })
})

describe('getApiToken', () => {
  beforeEach(() => {
    localStorage.clear()
    setToken('')
  })

  it('localStorage 有 token 时优先返回', () => {
    localStorage.setItem('copaw_auth_token', 'stored-token')
    expect(getApiToken()).toBe('stored-token')
  })

  it('localStorage 无 token 时 fallback 到 TOKEN 全局变量', () => {
    setToken('build-time-token')
    expect(getApiToken()).toBe('build-time-token')
  })

  it('两者均无时返回空字符串', () => {
    expect(getApiToken()).toBe('')
  })
})

describe('setAuthToken / clearAuthToken', () => {
  beforeEach(() => localStorage.clear())

  it('setAuthToken 写入 localStorage', () => {
    setAuthToken('my-token')
    expect(localStorage.getItem('copaw_auth_token')).toBe('my-token')
  })

  it('clearAuthToken 移除 localStorage 中的 token', () => {
    localStorage.setItem('copaw_auth_token', 'my-token')
    clearAuthToken()
    expect(localStorage.getItem('copaw_auth_token')).toBeNull()
  })

  it('clearAuthToken 后 getApiToken 返回空字符串', () => {
    setToken('')
    setAuthToken('my-token')
    clearAuthToken()
    expect(getApiToken()).toBe('')
  })
})
