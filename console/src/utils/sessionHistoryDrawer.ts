export const SESSION_HISTORY_DRAWER_STORAGE_KEY = "qwenpaw_history_panel_open";

export const OPEN_SESSION_HISTORY_DRAWER_EVENT =
  "qwenpaw:open-session-history-drawer";

export function requestSessionHistoryDrawerOpen(): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(SESSION_HISTORY_DRAWER_STORAGE_KEY, "true");
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }

  window.dispatchEvent(new Event(OPEN_SESSION_HISTORY_DRAWER_EVENT));
}
