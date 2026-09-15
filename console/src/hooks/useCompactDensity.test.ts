// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is false on tall viewports", () => {
    installMatchMedia(false);
    const { result } = renderHook(() => useCompactDensity());
    expect(result.current).toBe(false);
  });

  it("is true on short viewports", () => {
    installMatchMedia(true);
    const { result } = renderHook(() => useCompactDensity());
    expect(result.current).toBe(true);
  });

  it("follows live viewport changes", () => {
    const media = installMatchMedia(false);
    const { result } = renderHook(() => useCompactDensity());
    expect(result.current).toBe(false);

    act(() => media.setMatches(true));
    expect(result.current).toBe(true);

    act(() => media.setMatches(false));
    expect(result.current).toBe(false);
  });
});
