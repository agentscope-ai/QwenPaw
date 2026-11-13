import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useElementWidth } from "./useElementWidth";

type ROCallback = (entries: { contentRect: { width: number } }[]) => void;

let lastCallback: ROCallback | null = null;
const observe = vi.fn();
const disconnect = vi.fn();

beforeEach(() => {
  lastCallback = null;
  observe.mockClear();
  disconnect.mockClear();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(cb: ROCallback) {
        lastCallback = cb;
      }
      observe = observe;
      disconnect = disconnect;
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useElementWidth", () => {
  it("returns null before any measurement", () => {
    const { result } = renderHook(() => useElementWidth(null));
    expect(result.current).toBeNull();
  });

  it("observes the element and reports rounded widths", () => {
    const el = document.createElement("div");
    const { result } = renderHook(() => useElementWidth(el));
    expect(observe).toHaveBeenCalledWith(el);
    act(() => {
      lastCallback?.([{ contentRect: { width: 733.6 } }]);
    });
    expect(result.current).toBe(734);
  });

  it("disconnects on unmount", () => {
    const el = document.createElement("div");
    const { unmount } = renderHook(() => useElementWidth(el));
    unmount();
    expect(disconnect).toHaveBeenCalled();
  });
});
