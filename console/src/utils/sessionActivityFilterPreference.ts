import type { SessionActivityFilter } from "./sessionActivityFilter";

/**
 * Persisted activity-range filter for the sidebar session list.
 * Mirrors the `chatLayoutPreference` localStorage pattern so every
 * mounted session list stays in sync through a window event.
 */
const SESSION_ACTIVITY_FILTER_STORAGE_KEY = "qwenpaw_session_activity_filter";
export const SESSION_ACTIVITY_FILTER_CHANGE_EVENT =
  "qwenpaw:session-activity-filter-change";

export const DEFAULT_SESSION_ACTIVITY_FILTER: SessionActivityFilter = "all";

function isSessionActivityFilter(
  value: string | null,
): value is SessionActivityFilter {
  return (
    value === "all" ||
    value === "today" ||
    value === "week" ||
    value === "month"
  );
}

export function getSessionActivityFilterPreference(): SessionActivityFilter {
  try {
    const stored = localStorage.getItem(SESSION_ACTIVITY_FILTER_STORAGE_KEY);
    if (isSessionActivityFilter(stored)) {
      return stored;
    }
  } catch {
    // storage unavailable
  }
  return DEFAULT_SESSION_ACTIVITY_FILTER;
}

export function setSessionActivityFilterPreference(
  filter: SessionActivityFilter,
): void {
  try {
    localStorage.setItem(SESSION_ACTIVITY_FILTER_STORAGE_KEY, filter);
  } catch {
    // storage unavailable
  }

  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_ACTIVITY_FILTER_CHANGE_EVENT));
  }
}
