import { useCallback, useState } from "react";

const STORAGE_KEY = "qwenpaw_collapsed_date_groups_v1";

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return new Set(parsed);
      }
    }
  } catch {
    // Keep the safe default when storage is unavailable.
  }
  return new Set();
}

function saveCollapsed(groups: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...groups]));
  } catch {
    // Collapse state can remain memory-only.
  }
}

/**
 * Collapsed state of the date sections (pinned/today/week/month/older)
 * in the sidebar session list. Mirrors useCollapsedChatGroups so both
 * grouping modes offer the same fold interaction; persisted so the
 * layout survives remounts and reloads.
 */
export function useCollapsedDateGroups() {
  const [collapsedDateGroups, setCollapsedDateGroups] =
    useState<Set<string>>(loadCollapsed);

  const toggleDateGroup = useCallback((key: string) => {
    setCollapsedDateGroups((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      saveCollapsed(next);
      return next;
    });
  }, []);

  const expandDateGroup = useCallback((key: string) => {
    setCollapsedDateGroups((previous) => {
      if (!previous.has(key)) return previous;
      const next = new Set(previous);
      next.delete(key);
      saveCollapsed(next);
      return next;
    });
  }, []);

  return { collapsedDateGroups, toggleDateGroup, expandDateGroup };
}
