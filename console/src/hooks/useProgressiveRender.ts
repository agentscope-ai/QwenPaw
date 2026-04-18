import { useState, useEffect, useCallback } from "react";

const INITIAL_COUNT = 20;
const BATCH_SIZE = 20;

/**
 * Progressively renders a large list by initially showing a subset
 * and loading more items as the user scrolls to the bottom.
 *
 * Uses IntersectionObserver on a sentinel element to trigger loading,
 * keeping the existing layout (e.g. CSS Grid) completely untouched.
 *
 * Returns `sentinelRef` as a callback-ref setter so the observer is
 * correctly (re-)attached whenever the sentinel DOM element changes
 * (e.g. when switching between card / list view modes).
 */
export function useProgressiveRender<T>(items: T[]) {
  const [visibleCount, setVisibleCount] = useState(INITIAL_COUNT);
  const [sentinel, setSentinel] = useState<HTMLDivElement | null>(null);

  // Reset visible count when the source list changes (filter / sort / new data)
  useEffect(() => {
    setVisibleCount(INITIAL_COUNT);
  }, [items]);

  const loadMore = useCallback(() => {
    setVisibleCount((prev) => Math.min(prev + BATCH_SIZE, items.length));
  }, [items.length]);

  // Observe the sentinel element to trigger loading more items
  useEffect(() => {
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          loadMore();
        }
      },
      { rootMargin: "200px" },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore, sentinel]);

  const visibleItems = items.slice(0, visibleCount);
  const hasMore = visibleCount < items.length;

  return { visibleItems, hasMore, sentinelRef: setSentinel };
}
