/**
 * Persistent collapsed-state for the date groups of the session lists.
 *
 * Both SidebarSessionList and ChatSessionDrawer group conversations by
 * date and collapse the "month" / "older" groups by default. Keeping
 * that set in component state made it reset on every remount: after
 * navigating away and back, a conversation older than 7 days was hidden
 * inside a re-collapsed group and could not be found by scrolling.
 *
 * This hook persists the set to localStorage and exposes
 * `expandGroupForSession` so callers can force the group holding the
 * active conversation open.
 */
import { useCallback, useState } from "react";
import { getDateGroup, type DateGroup } from "../utils/sessionGrouping";

const STORAGE_KEY = "qwenpaw_collapsed_session_groups";

const DEFAULT_COLLAPSED: readonly DateGroup[] = ["month", "older"];

const VALID_GROUPS: ReadonlySet<string> = new Set([
  "pinned",
  "today",
  "week",
  "month",
  "older",
]);

function loadCollapsed(): Set<DateGroup> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return new Set(
          parsed.filter((g): g is DateGroup => VALID_GROUPS.has(g)),
        );
      }
    }
  } catch {
    // storage unavailable or corrupted — fall through to defaults
  }
  return new Set(DEFAULT_COLLAPSED);
}

function saveCollapsed(groups: Set<DateGroup>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...groups]));
  } catch {
    // storage unavailable — collapse state simply won't persist
  }
}

/** Minimal session shape needed to resolve its date group. */
interface GroupableSession {
  pinned?: boolean;
  updatedAt?: string | null;
  createdAt?: string | null;
}

export interface CollapsedSessionGroups {
  collapsedGroups: Set<DateGroup>;
  toggleGroup: (key: DateGroup) => void;
  /** Ensure the group containing `session` is expanded (visible). */
  expandGroupForSession: (session: GroupableSession) => void;
}

export function useCollapsedSessionGroups(): CollapsedSessionGroups {
  const [collapsedGroups, setCollapsedGroups] =
    useState<Set<DateGroup>>(loadCollapsed);

  const toggleGroup = useCallback((key: DateGroup) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      saveCollapsed(next);
      return next;
    });
  }, []);

  const expandGroupForSession = useCallback((session: GroupableSession) => {
    const group: DateGroup = session.pinned
      ? "pinned"
      : getDateGroup(session.updatedAt ?? session.createdAt);
    setCollapsedGroups((prev) => {
      if (!prev.has(group)) return prev;
      const next = new Set(prev);
      next.delete(group);
      saveCollapsed(next);
      return next;
    });
  }, []);

  return { collapsedGroups, toggleGroup, expandGroupForSession };
}
