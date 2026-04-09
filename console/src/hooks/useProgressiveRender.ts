import { useState, useEffect, useRef, useCallback } from "react";

const INITIAL_COUNT = 20;
const BATCH_SIZE = 20;

/**
 * Progressively renders a large list by initially showing a subset
 * and loading more items as the user scrolls to the bottom.
 *
 * Uses IntersectionObserver on a sentinel element to trigger loading,
 * keeping the existing layout (e.g. CSS Grid) completely untouched.
 */
export function useProgressiveRender<T>(items: T[]) {
  const [visibleCount, setVisibleCount] = useState(INITIAL_COUNT);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Reset visible count when the source list changes (filter / sort / new data)
  useEffect(() => {
    setVisibleCount(INITIAL_COUNT);
  }, [items]);

  const loadMore = useCallback(() => {
    setVisibleCount((prev) => Math.min(prev + BATCH_SIZE, items.length));
  }, [items.length]);

  // Observe the sentinel element to trigger loading more items
  useEffect(() => {
    const sentinel = sentinelRef.current;
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
  }, [loadMore]);

  const visibleItems = items.slice(0, visibleCount);
  const hasMore = visibleCount < items.length;

  return { visibleItems, hasMore, sentinelRef };
}
