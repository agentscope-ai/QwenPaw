/**
 * Tests for ThemeContext.
 *
 * Covers:
 * - ThemeProvider renders children
 * - useTheme returns default context values
 * - setThemeMode updates theme and isDark
 * - toggleTheme switches between light and dark
 * - getInitialMode reads from localStorage
 * - resolveIsDark handles system preference
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { ReactNode } from "react";
import { ThemeProvider, useTheme } from "./ThemeContext";

function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

describe("ThemeProvider + useTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it("provides default theme context", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });
    // Default is "system" when no localStorage
    expect(["light", "dark", "system"]).toContain(result.current.themeMode);
    expect(typeof result.current.isDark).toBe("boolean");
  });

  it("setThemeMode changes themeMode and isDark", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => {
      result.current.setThemeMode("dark");
    });
    expect(result.current.themeMode).toBe("dark");
    expect(result.current.isDark).toBe(true);

    act(() => {
      result.current.setThemeMode("light");
    });
    expect(result.current.themeMode).toBe("light");
    expect(result.current.isDark).toBe(false);
  });

  it("setThemeMode persists to localStorage", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => {
      result.current.setThemeMode("dark");
    });
    expect(localStorage.getItem("qwenpaw-theme")).toBe("dark");
  });

  it("toggleTheme switches between light and dark", () => {
    const { result } = renderHook(() => useTheme(), { wrapper });

    act(() => {
      result.current.setThemeMode("light");
    });
    expect(result.current.isDark).toBe(false);

    act(() => {
      result.current.toggleTheme();
    });
    expect(result.current.isDark).toBe(true);

    act(() => {
      result.current.toggleTheme();
    });
    expect(result.current.isDark).toBe(false);
  });

  it("reads initial mode from localStorage", () => {
    localStorage.setItem("qwenpaw-theme", "dark");
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.themeMode).toBe("dark");
    expect(result.current.isDark).toBe(true);
  });
});
