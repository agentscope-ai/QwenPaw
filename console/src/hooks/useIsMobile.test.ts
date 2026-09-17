import {
  describe,
  it,
  expect,
  vi,
  beforeAll,
  beforeEach,
  afterAll,
  afterEach,
} from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useIsMobile } from "./useIsMobile";

const mediaQueryListeners = new Set<() => void>();
const addMediaQueryListener = vi.fn((_event: string, listener: () => void) => {
  mediaQueryListeners.add(listener);
});
const removeMediaQueryListener = vi.fn(
  (_event: string, listener: () => void) => {
    mediaQueryListeners.delete(listener);
  },
);

const mobileMediaQuery = {
  get matches() {
    return window.innerWidth <= 768;
  },
  media: "(max-width: 768px)",
  onchange: null,
  addListener: vi.fn(),
  removeListener: vi.fn(),
  addEventListener: addMediaQueryListener,
  removeEventListener: removeMediaQueryListener,
  dispatchEvent: vi.fn(),
} as unknown as MediaQueryList;

// Helper to set the viewport used by the matchMedia test double.
function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", {
    writable: true,
    configurable: true,
    value: width,
  });
}

function dispatchMediaChange() {
  mediaQueryListeners.forEach((listener) => listener());
}

describe("useIsMobile", () => {
  const originalInnerWidth = window.innerWidth;
  const originalMatchMedia = window.matchMedia;

  beforeAll(() => {
    window.matchMedia = vi.fn(() => mobileMediaQuery);
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mediaQueryListeners.clear();
  });

  afterEach(() => {
    setViewport(originalInnerWidth);
  });

  afterAll(() => {
    window.matchMedia = originalMatchMedia;
  });

  // ---------------------------------------------------------------------------
  // Initial state (tri-state-ish: below / above breakpoint)
  // ---------------------------------------------------------------------------

  it("returns true when viewport is exactly at the breakpoint (768px)", () => {
    setViewport(768);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it("returns true when viewport is below the breakpoint (500px)", () => {
    setViewport(500);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it("returns false when viewport is above the breakpoint (1024px)", () => {
    setViewport(1024);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });

  // ---------------------------------------------------------------------------
  // Responsiveness to resize events
  // ---------------------------------------------------------------------------

  it("updates from false to true when the viewport shrinks below the breakpoint", () => {
    setViewport(1024);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    act(() => {
      setViewport(700);
      dispatchMediaChange();
    });

    expect(result.current).toBe(true);
  });

  it("updates from true to false when the viewport grows above the breakpoint", () => {
    setViewport(500);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);

    act(() => {
      setViewport(800);
      dispatchMediaChange();
    });

    expect(result.current).toBe(false);
  });

  it("stays false when resize keeps the viewport above the breakpoint", () => {
    setViewport(1024);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    act(() => {
      setViewport(1200);
      dispatchMediaChange();
    });

    expect(result.current).toBe(false);
  });

  it("stays true when resize keeps the viewport at the breakpoint", () => {
    setViewport(768);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);

    act(() => {
      setViewport(600);
      dispatchMediaChange();
    });

    expect(result.current).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // Cleanup
  // ---------------------------------------------------------------------------

  it("removes the media query listener on unmount", () => {
    setViewport(1024);
    const { result, unmount } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    unmount();
    expect(mediaQueryListeners.size).toBe(0);
    expect(removeMediaQueryListener).toHaveBeenCalledTimes(1);

    // Should not throw / update after unmount.
    expect(() => {
      setViewport(500);
      dispatchMediaChange();
    }).not.toThrow();
    expect(result.current).toBe(false);
  });

  it("shares one media query listener across hook instances", () => {
    const first = renderHook(() => useIsMobile());
    const second = renderHook(() => useIsMobile());

    expect(mediaQueryListeners.size).toBe(1);
    expect(addMediaQueryListener).toHaveBeenCalledTimes(1);

    first.unmount();
    expect(mediaQueryListeners.size).toBe(1);

    second.unmount();
    expect(mediaQueryListeners.size).toBe(0);
    expect(removeMediaQueryListener).toHaveBeenCalledTimes(1);
  });
});
