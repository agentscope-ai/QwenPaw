import { useEffect, useState } from "react";

import {
  getSidebarDensityPreference,
  SIDEBAR_DENSITY_CHANGE_EVENT,
} from "../utils/sidebarDensityPreference";

/**
 * Viewport height at or below which the "auto" density switches to
 * compact row metrics (small laptops, split-screen windows).
 *
 * The effective density is published on `<html data-sidebar-compact>`;
 * the session list stylesheets key their compact rules off that
 * attribute so the CSS and the virtualized row heights (the *_COMPACT
 * constants in SidebarSessionList.tsx) always agree.
 */
export const COMPACT_DENSITY_MEDIA_QUERY = "(max-height: 850px)";

function readMediaCompact(): boolean {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return false;
  }
  return window.matchMedia(COMPACT_DENSITY_MEDIA_QUERY).matches;
}

/**
 * Returns true when the session list should use compact row metrics:
 * always for the "compact" preference, never for "standard", and on
 * short viewports for "auto" (the default). Publishes the result on
 * the document element for the stylesheets. SSR-safe.
 */
export function useCompactDensity(): boolean {
  const [density, setDensity] = useState(getSidebarDensityPreference);
  const [mediaCompact, setMediaCompact] = useState(readMediaCompact);

  useEffect(() => {
    const syncDensity = () => {
      setDensity(getSidebarDensityPreference());
    };

    window.addEventListener(SIDEBAR_DENSITY_CHANGE_EVENT, syncDensity);
    return () => {
      window.removeEventListener(SIDEBAR_DENSITY_CHANGE_EVENT, syncDensity);
    };
  }, []);

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }

    const mediaQuery = window.matchMedia(COMPACT_DENSITY_MEDIA_QUERY);
    const syncMediaCompact = () => {
      setMediaCompact(mediaQuery.matches);
    };

    syncMediaCompact();
    mediaQuery.addEventListener("change", syncMediaCompact);

    return () => {
      mediaQuery.removeEventListener("change", syncMediaCompact);
    };
  }, []);

  const compact = density === "compact" || (density === "auto" && mediaCompact);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    if (compact) {
      root.dataset.sidebarCompact = "1";
    } else {
      delete root.dataset.sidebarCompact;
    }
  }, [compact]);

  return compact;
}
