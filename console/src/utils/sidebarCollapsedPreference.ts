const SIDEBAR_COLLAPSED_STORAGE_KEY = "qwenpaw_sidebar_collapsed";

/**
 * Read the persisted sidebar collapsed preference.
 *
 * The default is expanded: an absent or malformed key resolves to false so
 * a fresh profile never starts with a hidden navigation surface.
 */
export function getSidebarCollapsedPreference(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

/**
 * Persist the sidebar collapsed preference set by an explicit user toggle.
 *
 * The expanded state removes the key instead of writing "false" so the
 * default stays storage-free. Callers must not use this for transient,
 * viewport-driven collapsing (see the mobile override in Sidebar.tsx).
 */
export function setSidebarCollapsedPreference(collapsed: boolean): void {
  try {
    if (collapsed) {
      localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, "true");
    } else {
      localStorage.removeItem(SIDEBAR_COLLAPSED_STORAGE_KEY);
    }
  } catch {
    // storage unavailable
  }
}
