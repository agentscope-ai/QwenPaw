import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useIsMobile } from "./useIsMobile";

// Helper to set window dimensions and dispatch a resize event.
function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", {
    writable: true,
    configurable: true,
    value: width,
  });
}

function dispatchResize() {
  window.dispatchEvent(new Event("resize"));
}

describe("useIsMobile", () => {
  const originalInnerWidth = window.innerWidth;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    setViewport(originalInnerWidth);
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
      dispatchResize();
    });

    expect(result.current).toBe(true);
  });

  it("updates from true to false when the viewport grows above the breakpoint", () => {
    setViewport(500);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);

    act(() => {
      setViewport(800);
      dispatchResize();
    });

    expect(result.current).toBe(false);
  });

  it("stays false when resize keeps the viewport above the breakpoint", () => {
    setViewport(1024);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    act(() => {
      setViewport(1200);
      dispatchResize();
    });

    expect(result.current).toBe(false);
  });

  it("stays true when resize keeps the viewport at the breakpoint", () => {
    setViewport(768);
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);

    act(() => {
      setViewport(600);
      dispatchResize();
    });

    expect(result.current).toBe(true);
  });

  // ---------------------------------------------------------------------------
  // Cleanup
  // ---------------------------------------------------------------------------

  it("removes the resize listener on unmount (no state update after unmount)", () => {
    setViewport(1024);
    const { result, unmount } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);

    unmount();

    // Should not throw / update after unmount.
    expect(() => {
      setViewport(500);
      dispatchResize();
    }).not.toThrow();
    expect(result.current).toBe(false);
  });
});
