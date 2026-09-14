import { useCallback, useRef, useState } from "react";

const STORAGE_KEY = "qwenpaw_collapsed_chat_groups_v4";
const LEGACY_STORAGE_KEY = "qwenpaw_collapsed_chat_groups_v3";
const CRON_GROUP_ID = "cron";
const SUBAGENT_GROUP_ID = "subagents";

interface CollapsedState {
  groups: Set<string>;
  hasPersistedState: boolean;
}

function loadCollapsed(): CollapsedState {
  try {
    const currentRaw = localStorage.getItem(STORAGE_KEY);
    const legacyRaw = localStorage.getItem(LEGACY_STORAGE_KEY);
    const raw = currentRaw ?? legacyRaw;
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const isLegacyDefault =
          !currentRaw &&
          parsed.length === 2 &&
          parsed.includes(CRON_GROUP_ID) &&
          parsed.includes(SUBAGENT_GROUP_ID);
        return {
          groups: new Set(parsed),
          hasPersistedState: !isLegacyDefault,
        };
      }
    }
  } catch {
    // Keep the safe default when storage is unavailable.
  }
  return {
    groups: new Set([CRON_GROUP_ID, SUBAGENT_GROUP_ID]),
    hasPersistedState: false,
  };
}

function saveCollapsed(groups: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...groups]));
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // Collapse state can remain memory-only.
  }
}

export function useCollapsedChatGroups() {
  const [initialState] = useState<CollapsedState>(loadCollapsed);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    initialState.groups,
  );
  const defaultsInitializedRef = useRef(initialState.hasPersistedState);

  const initializeCollapsedGroups = useCallback(
    (defaultGroups: ReadonlySet<string>) => {
      if (defaultsInitializedRef.current || defaultGroups.size === 0) return;
      defaultsInitializedRef.current = true;
      setCollapsedGroups((previous) => {
        const next = new Set(previous);
        defaultGroups.forEach((groupId) => next.add(groupId));
        saveCollapsed(next);
        return next;
      });
    },
    [],
  );

  const toggleGroup = useCallback((groupId: string) => {
    defaultsInitializedRef.current = true;
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

  return {
    collapsedGroups,
    toggleGroup,
    expandGroup,
    initializeCollapsedGroups,
  };
}
