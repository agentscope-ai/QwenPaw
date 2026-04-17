import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import LanguageSwitcher from '../index'

// vi.hoisted 保证变量在 vi.mock hoist 之前就初始化
const { mockChangeLanguage, mockUpdateLanguage } = vi.hoisted(() => ({
  mockChangeLanguage: vi.fn(),
  mockUpdateLanguage: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    i18n: {
      language: 'en',
      resolvedLanguage: 'en',
      changeLanguage: mockChangeLanguage,
    },
    t: (k: string) => k,
  }),
}))

vi.mock('@/api/modules/language', () => ({
  languageApi: { updateLanguage: mockUpdateLanguage },
}))

vi.mock('@agentscope-ai/design', () => ({
  Dropdown: ({
    children,
    menu,
  }: {
    children: React.ReactNode
    menu: { items: Array<{ key: string; label: string; onClick: () => void }> }
  }) => (
    <div>
      {children}
      <ul role="menu">
        {menu.items?.map((item) => (
          <li key={item.key} role="menuitem" onClick={item.onClick}>
            {item.label}
          </li>
        ))}
      </ul>
    </div>
  ),
}))

describe('LanguageSwitcher', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.clearAllMocks())

  it('渲染语言切换按钮', () => {
    renderWithProviders(<LanguageSwitcher />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('展示 4 种语言选项', () => {
    renderWithProviders(<LanguageSwitcher />)
    expect(screen.getByText('English')).toBeInTheDocument()
    expect(screen.getByText('简体中文')).toBeInTheDocument()
    expect(screen.getByText('日本語')).toBeInTheDocument()
    expect(screen.getByText('Русский')).toBeInTheDocument()
  })

  it('点击语言选项调用 i18n.changeLanguage', async () => {
    const user = userEvent.setup()
    renderWithProviders(<LanguageSwitcher />)
    await user.click(screen.getByText('简体中文'))
    expect(mockChangeLanguage).toHaveBeenCalledWith('zh')
  })

  it('切换语言后写入 localStorage', async () => {
    const user = userEvent.setup()
    renderWithProviders(<LanguageSwitcher />)
    await user.click(screen.getByText('日本語'))
    expect(localStorage.getItem('language')).toBe('ja')
  })

  it('切换语言后调用 languageApi.updateLanguage', async () => {
    const user = userEvent.setup()
    renderWithProviders(<LanguageSwitcher />)
    await user.click(screen.getByText('English'))
    expect(mockUpdateLanguage).toHaveBeenCalledWith('en')
  })
})
