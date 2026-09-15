/**
 * Sidebar session list density preference ("conversation height").
 *
 * - "auto": compact rows on short viewports (see useCompactDensity)
 * - "standard": always full-height rows
 * - "compact": always compact rows
 *
 * Mirrors the `chatLayoutPreference` localStorage pattern so every
 * mounted surface stays in sync through a window event.
 */
export type SidebarDensity = "auto" | "standard" | "compact";

const SIDEBAR_DENSITY_STORAGE_KEY = "qwenpaw_sidebar_density";
export const SIDEBAR_DENSITY_CHANGE_EVENT = "qwenpaw:sidebar-density-change";

const DEFAULT_SIDEBAR_DENSITY: SidebarDensity = "auto";

function isSidebarDensity(value: string | null): value is SidebarDensity {
  return value === "auto" || value === "standard" || value === "compact";
}

export function getSidebarDensityPreference(): SidebarDensity {
  try {
    const stored = localStorage.getItem(SIDEBAR_DENSITY_STORAGE_KEY);
    if (isSidebarDensity(stored)) {
      return stored;
    }
  } catch {
    // storage unavailable
  }
  return DEFAULT_SIDEBAR_DENSITY;
}

export function setSidebarDensityPreference(density: SidebarDensity): void {
  try {
    localStorage.setItem(SIDEBAR_DENSITY_STORAGE_KEY, density);
  } catch {
    // storage unavailable
  }

  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SIDEBAR_DENSITY_CHANGE_EVENT));
  }
}
