/**
 * useElementWidth.ts — Observe an element's content width via ResizeObserver.
 *
 * Returns the rounded width in px, or null before the first measurement /
 * when the element or ResizeObserver is unavailable (consumers fall back to
 * viewport-based behaviour).
 */
import { useEffect, useState } from "react";

export function useElementWidth(el: HTMLElement | null): number | null {
  const [width, setWidth] = useState<number | null>(null);

  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") {
      setWidth(null);
      return;
    }
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w != null) {
        setWidth(Math.round(w));
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);

  return width;
}
