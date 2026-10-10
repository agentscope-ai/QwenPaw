/**
 * Tests for FxTierContext.
 *
 * Covers:
 * - resolveFxTier maps the system preference from the OS setting
 * - explicit preferences (full / reduced / off) pass through unchanged
 * - the effective tier is written to <html data-fx-tier>
 * - setFxTierPreference persists to localStorage
 * - OS reduced-motion changes are followed dynamically (system only)
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { ReactNode } from "react";
import { FxTierProvider, resolveFxTier, useFxTier } from "./FxTierContext";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function wrapper({ children }: { children: ReactNode }) {
  return <FxTierProvider>{children}</FxTierProvider>;
}

/** Stateful matchMedia mock: flipping reduced-motion fires change listeners. */
function createMatchMediaMock() {
  let reduced = false;
  let changeHandler: ((event: { matches: boolean }) => void) | null = null;

  const matchMedia = vi.fn((query: string) => ({
    get matches() {
      return query === REDUCED_MOTION_QUERY ? reduced : false;
    },
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(
      (type: string, handler: (event: { matches: boolean }) => void) => {
        if (type === "change") changeHandler = handler;
      },
    ),
    removeEventListener: vi.fn(
      (type: string, handler: (event: { matches: boolean }) => void) => {
        if (type === "change" && changeHandler === handler) {
          changeHandler = null;
        }
      },
    ),
    dispatchEvent: vi.fn(),
  }));

  return {
    matchMedia,
    setReducedMotion(value: boolean) {
      reduced = value;
      changeHandler?.({ matches: value });
    },
  };
}

describe("resolveFxTier", () => {
  it("maps system to reduced only when the OS requests reduced motion", () => {
    expect(resolveFxTier("system", false)).toBe("full");
    expect(resolveFxTier("system", true)).toBe("reduced");
  });

  it("passes explicit preferences through unchanged", () => {
    expect(resolveFxTier("full", true)).toBe("full");
    expect(resolveFxTier("reduced", false)).toBe("reduced");
    expect(resolveFxTier("off", false)).toBe("off");
  });
});

describe("FxTierProvider + useFxTier", () => {
  let setReducedMotion: (value: boolean) => void;

  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.fxTier;
    const mock = createMatchMediaMock();
    setReducedMotion = mock.setReducedMotion;
    (window as unknown as { matchMedia: unknown }).matchMedia = mock.matchMedia;
  });

  it("defaults to the system preference and resolves to full", () => {
    const { result } = renderHook(() => useFxTier(), { wrapper });
    expect(result.current.fxTierPreference).toBe("system");
    expect(result.current.fxTier).toBe("full");
    expect(document.documentElement.dataset.fxTier).toBe("full");
  });

  it("resolves system to reduced when the OS requests reduced motion", () => {
    setReducedMotion(true);
    const { result } = renderHook(() => useFxTier(), { wrapper });
    expect(result.current.fxTier).toBe("reduced");
    expect(document.documentElement.dataset.fxTier).toBe("reduced");
  });

  it("writes explicit tiers to the DOM attribute", () => {
    const { result } = renderHook(() => useFxTier(), { wrapper });

    act(() => {
      result.current.setFxTierPreference("off");
    });
    expect(result.current.fxTier).toBe("off");
    expect(document.documentElement.dataset.fxTier).toBe("off");

    act(() => {
      result.current.setFxTierPreference("reduced");
    });
    expect(result.current.fxTier).toBe("reduced");
    expect(document.documentElement.dataset.fxTier).toBe("reduced");
  });

  it("setFxTierPreference persists to localStorage", () => {
    const { result } = renderHook(() => useFxTier(), { wrapper });

    act(() => {
      result.current.setFxTierPreference("off");
    });
    expect(localStorage.getItem("qwenpaw-fx-tier")).toBe("off");
  });

  it("reads the initial preference from localStorage", () => {
    localStorage.setItem("qwenpaw-fx-tier", "off");
    const { result } = renderHook(() => useFxTier(), { wrapper });
    expect(result.current.fxTierPreference).toBe("off");
    expect(result.current.fxTier).toBe("off");
  });

  it("follows OS reduced-motion changes while on the system preference", () => {
    const { result } = renderHook(() => useFxTier(), { wrapper });
    expect(result.current.fxTier).toBe("full");

    act(() => {
      setReducedMotion(true);
    });
    expect(result.current.fxTier).toBe("reduced");
    expect(document.documentElement.dataset.fxTier).toBe("reduced");
  });

  it("ignores OS reduced-motion changes for explicit preferences", () => {
    const { result } = renderHook(() => useFxTier(), { wrapper });

    act(() => {
      result.current.setFxTierPreference("off");
    });

    act(() => {
      setReducedMotion(true);
    });
    expect(result.current.fxTier).toBe("off");
  });
});
