// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSidebarDensityPreference } from "../utils/sidebarDensityPreference";
import {
  COMPACT_DENSITY_MEDIA_QUERY,
  useCompactDensity,
} from "./useCompactDensity";

type ChangeListener = (event: { matches: boolean }) => void;

function installMatchMedia(initialMatches: boolean) {
  const listeners = new Set<ChangeListener>();
  let matches = initialMatches;
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    get matches() {
      return query === COMPACT_DENSITY_MEDIA_QUERY ? matches : false;
    },
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: (_event: string, listener: ChangeListener) => {
      listeners.add(listener);
    },
    removeEventListener: (_event: string, listener: ChangeListener) => {
      listeners.delete(listener);
    },
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia;

  return {
    setMatches(next: boolean) {
      matches = next;
      listeners.forEach((listener) => listener({ matches: next }));
    },
  };
}

describe("useCompactDensity", () => {
  beforeEach(() => {
    localStorage.removeItem("qwenpaw_sidebar_density");
    delete document.documentElement.dataset.sidebarCompact;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("follows the viewport in auto mode", () => {
    const media = installMatchMedia(false);
    const { result } = renderHook(() => useCompactDensity());
    expect(result.current).toBe(false);

    act(() => media.setMatches(true));
    expect(result.current).toBe(true);

    act(() => media.setMatches(false));
    expect(result.current).toBe(false);
  });

  it("forces compact regardless of the viewport", () => {
    installMatchMedia(false);
    localStorage.setItem("qwenpaw_sidebar_density", "compact");
    const { result } = renderHook(() => useCompactDensity());
    expect(result.current).toBe(true);
  });

  it("forces standard regardless of the viewport", () => {
    installMatchMedia(true);
    localStorage.setItem("qwenpaw_sidebar_density", "standard");
    const { result } = renderHook(() => useCompactDensity());
    expect(result.current).toBe(false);
  });

  it("reacts to preference changes while mounted", () => {
    installMatchMedia(false);
    const { result } = renderHook(() => useCompactDensity());
    expect(result.current).toBe(false);

    act(() => setSidebarDensityPreference("compact"));
    expect(result.current).toBe(true);
  });

  it("publishes the effective density on the document element", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useCompactDensity());
    expect(result.current).toBe(true);
    expect(document.documentElement.dataset.sidebarCompact).toBe("1");

    act(() => setSidebarDensityPreference("standard"));
    expect(result.current).toBe(false);
    expect(document.documentElement.dataset.sidebarCompact).toBeUndefined();
  });
});
