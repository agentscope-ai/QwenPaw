import { useEffect, useRef, useState } from "react";

const USER_BUBBLE_SELECTOR = '[class*="bubble-end"]';

/**
 * Hook that uses IntersectionObserver to detect which user message bubble
 * is currently most visible within the chat scroll container.
 * Returns the index of the active user message (0-based among user messages).
 */
export function useActiveUserMessageIndex(
  userMessageCount: number,
): number {
  const [activeIndex, setActiveIndex] = useState(-1);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const visibleMapRef = useRef<Map<number, number>>(new Map());

  useEffect(() => {
    // Clean up previous observer
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }
    visibleMapRef.current.clear();

    if (userMessageCount === 0) {
      setActiveIndex(-1);
      return;
    }

    // Find the scroll container (chatMessagesArea)
    const scrollContainer = document.querySelector(
      '[class*="chatMessagesArea"]',
    );
    if (!scrollContainer) return;

    // Find all user bubbles
    const bubbles = scrollContainer.querySelectorAll(USER_BUBBLE_SELECTOR);
    if (bubbles.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const idx = Number(
            (entry.target as HTMLElement).dataset.__thumbnailIdx,
          );
          if (Number.isNaN(idx)) continue;

          if (entry.isIntersecting) {
            visibleMapRef.current.set(idx, entry.intersectionRatio);
          } else {
            visibleMapRef.current.delete(idx);
          }
        }

        // Pick the one with highest intersection ratio
        let bestIdx = -1;
        let bestRatio = 0;
        visibleMapRef.current.forEach((ratio, idx) => {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestIdx = idx;
          }
        });
        setActiveIndex(bestIdx);
      },
      {
        root: scrollContainer,
        threshold: [0, 0.25, 0.5, 0.75, 1],
      },
    );

    // Observe each user bubble and tag it with an index
    bubbles.forEach((el, idx) => {
      (el as HTMLElement).dataset.__thumbnailIdx = String(idx);
      observer.observe(el);
    });

    observerRef.current = observer;

    return () => {
      observer.disconnect();
    };
  }, [userMessageCount]);

  return activeIndex;
}
