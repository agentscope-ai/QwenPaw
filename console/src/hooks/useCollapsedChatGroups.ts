import { useCallback, useState } from "react";

const STORAGE_KEY = "qwenpaw_collapsed_chat_groups_v3";
const CRON_GROUP_ID = "cron";
const SUBAGENT_GROUP_ID = "subagents";

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return new Set(parsed);
    }
  } catch {
    // Keep the safe default when storage is unavailable.
  }
  return new Set([CRON_GROUP_ID, SUBAGENT_GROUP_ID]);
}

function saveCollapsed(groups: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...groups]));
  } catch {
    // Collapse state can remain memory-only.
  }
}

export function useCollapsedChatGroups() {
  const [collapsedGroups, setCollapsedGroups] =
    useState<Set<string>>(loadCollapsed);

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsedGroups((previous) => {
      const next = new Set(previous);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      saveCollapsed(next);
      return next;
    });
  }, []);

  const expandGroup = useCallback((groupId: string) => {
    setCollapsedGroups((previous) => {
      if (!previous.has(groupId)) return previous;
      const next = new Set(previous);
      next.delete(groupId);
      saveCollapsed(next);
      return next;
    });
  }, []);

  return { collapsedGroups, toggleGroup, expandGroup };
}
