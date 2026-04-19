import { describe, it, expect, vi } from 'vitest'
import { screen, fireEvent } from '@testing-library/react'
import ThemeToggleButton from './index'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { render } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Wrap with real ThemeProvider, control initial theme via localStorage
function renderWithTheme(mode: 'light' | 'dark' | 'system' = 'light') {
  localStorage.setItem('qwenpaw-theme', mode)
  return render(
    <ThemeProvider>
      <ThemeToggleButton />
    </ThemeProvider>,
  )
}

describe('ThemeToggleButton', () => {
  it('renders the theme toggle button', () => {
    renderWithTheme('light')
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('shows sun icon when light mode is active', () => {
    renderWithTheme('light')
    expect(document.querySelector('[data-icon="SparkSunLine"]')).toBeInTheDocument()
  })

  it('shows moon icon when dark mode is active', () => {
    renderWithTheme('dark')
    expect(document.querySelector('[data-icon="SparkMoonLine"]')).toBeInTheDocument()
  })

  it('shows computer icon when system mode is active', () => {
    renderWithTheme('system')
    expect(document.querySelector('[data-icon="SparkComputerLine"]')).toBeInTheDocument()
  })

  it('renders without crashing', () => {
    expect(() => renderWithTheme('light')).not.toThrow()
  })
})
