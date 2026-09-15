import { useEffect, useState } from "react";

/**
 * Viewport height at or below which dense lists switch to compact row
 * metrics (small laptops, split-screen windows).
 *
 * Keep in sync with the `@media (max-height: 850px)` blocks in
 * sessionItem / SessionGroupHeader / SessionDateHeader /
 * sidebarSessionList stylesheets: the virtualized list allocates the
 * JS height constants while the media queries render the matching CSS.
 */
export const COMPACT_DENSITY_MEDIA_QUERY = "(max-height: 850px)";

function readCompactDensity(): boolean {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return false;
  }
  return window.matchMedia(COMPACT_DENSITY_MEDIA_QUERY).matches;
}

/**
 * Returns true when the viewport is short enough that the session list
 * should use compact row metrics. Follows live viewport changes (window
 * resize, zoom, moving to an external display). SSR-safe: defaults to
 * false when window or matchMedia is unavailable.
 */
export function useCompactDensity(): boolean {
  const [compact, setCompact] = useState(readCompactDensity);

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }

    const mediaQuery = window.matchMedia(COMPACT_DENSITY_MEDIA_QUERY);
    const syncCompactDensity = () => {
      setCompact(mediaQuery.matches);
    };

    syncCompactDensity();
    mediaQuery.addEventListener("change", syncCompactDensity);

    return () => {
      mediaQuery.removeEventListener("change", syncCompactDensity);
    };
  }, []);

  return compact;
}
