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

// Wrap with real ThemeProvider, control initial theme via localStorage
function renderWithTheme(isDarkMode: boolean) {
  localStorage.setItem('copaw-theme', isDarkMode ? 'dark' : 'light')
  return render(
    <ThemeProvider>
      <ThemeToggleButton />
    </ThemeProvider>,
  )
}

describe('ThemeToggleButton', () => {
  it('shows moon icon in light mode', () => {
    renderWithTheme(false)
    expect(screen.getByRole('img', { name: 'moon' })).toBeInTheDocument()
  })

  it('shows sun icon in dark mode', () => {
    renderWithTheme(true)
    expect(screen.getByRole('img', { name: 'sun' })).toBeInTheDocument()
  })

  it('aria-label contains switchToDark in light mode', () => {
    renderWithTheme(false)
    expect(
      screen.getByRole('button', { name: 'theme.switchToDark' }),
    ).toBeInTheDocument()
  })

  it('aria-label contains switchToLight in dark mode', () => {
    renderWithTheme(true)
    expect(
      screen.getByRole('button', { name: 'theme.switchToLight' }),
    ).toBeInTheDocument()
  })

  it('clicking the button toggles theme from light to dark', async () => {
    const user = userEvent.setup()
    renderWithTheme(false)
    const btn = screen.getByRole('button')
    await user.click(btn)
    expect(screen.getByRole('img', { name: 'sun' })).toBeInTheDocument()
  })
})
