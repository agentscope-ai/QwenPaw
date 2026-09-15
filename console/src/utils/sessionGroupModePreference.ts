/**
 * Session list grouping mode preference.
 *
 * Controls how the sidebar conversation history sections sessions:
 * - "date": by recency bucket (pinned/today/week/month/older)
 * - "source": by chat group (uncategorized/cron/subagents/custom)
 * - "none": a single flat recency list
 *
 * Mirrors the `chatLayoutPreference` localStorage pattern so every
 * mounted session list stays in sync through a window event.
 */
export type SessionGroupMode = "date" | "source" | "none";

const SESSION_GROUP_MODE_STORAGE_KEY = "qwenpaw_session_group_mode";
export const SESSION_GROUP_MODE_CHANGE_EVENT =
  "qwenpaw:session-group-mode-change";

export const DEFAULT_SESSION_GROUP_MODE: SessionGroupMode = "date";

function isSessionGroupMode(value: string | null): value is SessionGroupMode {
  return value === "date" || value === "source" || value === "none";
}

export function getSessionGroupModePreference(): SessionGroupMode {
  try {
    const stored = localStorage.getItem(SESSION_GROUP_MODE_STORAGE_KEY);
    if (isSessionGroupMode(stored)) {
      return stored;
    }
  } catch {
    // storage unavailable
  }
  return DEFAULT_SESSION_GROUP_MODE;
}

export function setSessionGroupModePreference(mode: SessionGroupMode): void {
  try {
    localStorage.setItem(SESSION_GROUP_MODE_STORAGE_KEY, mode);
  } catch {
    // storage unavailable
  }

  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_GROUP_MODE_CHANGE_EVENT));
  }
}
