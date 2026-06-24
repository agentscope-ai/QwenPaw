import { useCallback, useEffect, useRef, useState } from "react";

export interface UserMessageSnapshot {
  /** Unique key for React */
  id: string;
  /** Extracted plain text from the bubble */
  text: string;
  /** Formatted time string extracted from bubble footer */
  timeLabel: string;
  /** Index among visible user bubbles (0 = topmost) */
  index: number;
  /** DOM element reference */
  element: HTMLElement;
}

const USER_BUBBLE_SELECTOR = '[class*="bubble-list"] > [class*="bubble-end"]';
const POLL_INTERVAL_MS = 800;

/**
 * Hook that reads user message bubbles directly from the DOM.
 * Only returns bubbles that are actually rendered (handles lazy loading).
 */
export function useUserMessageSnapshot(): {
  snapshots: UserMessageSnapshot[];
  refresh: () => void;
} {
  const [snapshots, setSnapshots] = useState<UserMessageSnapshot[]>([]);
  const prevCountRef = useRef(0);

  const derive = useCallback(() => {
    const area = document.querySelector('[class*="chatMessagesArea"]');
    if (!area) return;

    const bubbles = Array.from(
      area.querySelectorAll(USER_BUBBLE_SELECTOR),
    ).sort(
      (a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top,
    ) as HTMLElement[];

    // Only update when count changes
    if (bubbles.length === prevCountRef.current) return;
    prevCountRef.current = bubbles.length;

    const next: UserMessageSnapshot[] = bubbles.map((el, idx) => {
      // Extract text from bubble content
      const contentEl = el.querySelector('[class*="markdown"]');
      const rawText = (contentEl?.textContent || el.textContent || "").trim();
      const text = rawText.split("\n")[0]?.trim() || "";

      // Extract time label from bubble footer
      const footerEl = el.querySelector('[class*="bubble-footer"]');
      const timeLabel = footerEl?.textContent?.trim() || "";

      return {
        id: el.id || `dom-bubble-${idx}`,
        text,
        timeLabel,
        index: idx,
        element: el,
      };
    });

    setSnapshots(next);
  }, []);

  useEffect(() => {
    derive();
    const timer = setInterval(derive, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [derive]);

  return { snapshots, refresh: derive };
}
