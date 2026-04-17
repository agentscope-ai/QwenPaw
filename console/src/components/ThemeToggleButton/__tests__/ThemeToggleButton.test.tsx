import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/common_setup'
import ThemeToggleButton from '../index'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { render } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// 用真实 ThemeProvider 包裹，通过 localStorage 控制初始主题
function renderWithTheme(isDarkMode: boolean) {
  localStorage.setItem('copaw-theme', isDarkMode ? 'dark' : 'light')
  return render(
    <ThemeProvider>
      <ThemeToggleButton />
    </ThemeProvider>,
  )
}

describe('ThemeToggleButton', () => {
  it('light 模式显示 moon 图标', () => {
    renderWithTheme(false)
    // MoonOutlined 的 aria-label
    expect(screen.getByRole('img', { name: 'moon' })).toBeInTheDocument()
  })

  it('dark 模式显示 sun 图标', () => {
    renderWithTheme(true)
    expect(screen.getByRole('img', { name: 'sun' })).toBeInTheDocument()
  })

  it('light 模式 aria-label 包含 switchToDark', () => {
    renderWithTheme(false)
    expect(
      screen.getByRole('button', { name: 'theme.switchToDark' }),
    ).toBeInTheDocument()
  })

  it('dark 模式 aria-label 包含 switchToLight', () => {
    renderWithTheme(true)
    expect(
      screen.getByRole('button', { name: 'theme.switchToLight' }),
    ).toBeInTheDocument()
  })

  it('点击按钮切换主题（light → dark）', async () => {
    const user = userEvent.setup()
    renderWithTheme(false)
    const btn = screen.getByRole('button')
    await user.click(btn)
    // 切换后应显示 sun
    expect(screen.getByRole('img', { name: 'sun' })).toBeInTheDocument()
  })
})
