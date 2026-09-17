import { renderHook, act } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { useProgressiveRender } from "./useProgressiveRender";

// Capture the IntersectionObserver callback so we can fire it manually in tests
let intersectionCallback:
  | ((entries: IntersectionObserverEntry[]) => void)
  | null = null;

beforeEach(() => {
  intersectionCallback = null;

  // Must be a real constructor (function, not arrow) so `new IntersectionObserver(...)` works
  global.IntersectionObserver = vi.fn(function (
    this: unknown,
    cb: (entries: IntersectionObserverEntry[]) => void,
  ) {
    intersectionCallback = cb;
    return {
      observe: vi.fn(),
      unobserve: vi.fn(),
      disconnect: vi.fn(),
    };
  }) as unknown as typeof IntersectionObserver;
});

// Helper: fire the captured IntersectionObserver as if sentinel is intersecting
function triggerIntersection() {
  intersectionCallback?.([
    { isIntersecting: true } as IntersectionObserverEntry,
  ]);
}

describe("useProgressiveRender", () => {
  it("shows all items when total < INITIAL_COUNT (10 items)", () => {
    const items = Array.from({ length: 10 }, (_, i) => i);
    const { result } = renderHook(() => useProgressiveRender(items));

    expect(result.current.visibleItems).toHaveLength(10);
    expect(result.current.visibleItems).toEqual(items);
    expect(result.current.hasMore).toBe(false);
  });

  it("shows only INITIAL_COUNT (20) items when total > INITIAL_COUNT (50 items)", () => {
    const items = Array.from({ length: 50 }, (_, i) => i);
    const { result } = renderHook(() => useProgressiveRender(items));

    expect(result.current.visibleItems).toHaveLength(20);
    expect(result.current.hasMore).toBe(true);
  });

  it("loadMore (via IntersectionObserver) increases visibleItems by BATCH_SIZE", () => {
    const items = Array.from({ length: 100 }, (_, i) => i);
    const { result } = renderHook(() => useProgressiveRender(items));

    // Initial state: 20 visible
    expect(result.current.visibleItems).toHaveLength(20);

    // Attach a sentinel so the observer is created, then fire intersection
    act(() => {
      result.current.sentinelRef(document.createElement("div"));
    });

    act(() => {
      triggerIntersection();
    });

    expect(result.current.visibleItems).toHaveLength(40);
    expect(result.current.hasMore).toBe(true);
  });

  it("loadMore clamps at items.length and does not exceed total", () => {
    // 25 items: initial=20, one loadMore should show all 25, not 40
    const items = Array.from({ length: 25 }, (_, i) => i);
    const { result } = renderHook(() => useProgressiveRender(items));

    expect(result.current.visibleItems).toHaveLength(20);
    expect(result.current.hasMore).toBe(true);

    act(() => {
      result.current.sentinelRef(document.createElement("div"));
    });

    act(() => {
      triggerIntersection();
    });

    expect(result.current.visibleItems).toHaveLength(25);
    expect(result.current.hasMore).toBe(false);
  });

  it("resets visibleCount to INITIAL_COUNT when items prop changes", () => {
    const items50 = Array.from({ length: 50 }, (_, i) => i);
    const items5 = Array.from({ length: 5 }, (_, i) => i + 100);

    const { result, rerender } = renderHook(
      ({ items }: { items: number[] }) => useProgressiveRender(items),
      { initialProps: { items: items50 } },
    );

    // Initially 50 items → 20 visible
    expect(result.current.visibleItems).toHaveLength(20);
    expect(result.current.hasMore).toBe(true);

    // Switch to a new shorter list
    rerender({ items: items5 });

    // visibleCount resets to INITIAL_COUNT (20), but list only has 5 → all shown
    expect(result.current.visibleItems).toHaveLength(5);
    expect(result.current.visibleItems).toEqual(items5);
    expect(result.current.hasMore).toBe(false);
  });
});
