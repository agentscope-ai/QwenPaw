import { useCallback, useEffect, useMemo } from "react";
import { useSessionStore } from "../stores/sessionStore";
import { useChatStore } from "../stores/chatStore";
import type { ChatSession, SessionGroup } from "../types";

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseChatSessionsReturn {
  sessions: ChatSession[];
  groupedSessions: SessionGroup[];
  loading: boolean;
  activeSessionId: string | null;
  searchQuery: string;

  // Actions
  selectSession: (id: string) => void;
  createSession: () => Promise<string>;
  deleteSession: (id: string) => Promise<void>;
  renameSession: (id: string, name: string) => Promise<void>;
  pinSession: (id: string, pinned: boolean) => Promise<void>;
  setSearchQuery: (query: string) => void;
  refresh: () => Promise<void>;
}

export function useChatSessions(): UseChatSessionsReturn {
  const allSessions = useSessionStore((s) => s.sessions);
  const loading = useSessionStore((s) => s.loading);
  const searchQuery = useSessionStore((s) => s.searchQuery);
  const activeSessionId = useChatStore((s) => s.activeSessionId);

  const sessions = useMemo(() => {
    if (!searchQuery.trim()) return allSessions;
    const q = searchQuery.toLowerCase();
    return allSessions.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.lastMessage && s.lastMessage.toLowerCase().includes(q)),
    );
  }, [allSessions, searchQuery]);

  const groupedSessions = useMemo(() => {
    const pinned = sessions.filter((s) => s.pinned);
    const unpinned = sessions.filter((s) => !s.pinned);

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today.getTime() - 86400000);
    const weekAgo = new Date(today.getTime() - 7 * 86400000);
    const monthAgo = new Date(today.getTime() - 30 * 86400000);

    const buckets: Record<string, ChatSession[]> = {
      today: [],
      yesterday: [],
      thisWeek: [],
      thisMonth: [],
      older: [],
    };

    for (const s of unpinned) {
      const date = new Date(s.createdAt);
      if (date >= today) buckets.today.push(s);
      else if (date >= yesterday) buckets.yesterday.push(s);
      else if (date >= weekAgo) buckets.thisWeek.push(s);
      else if (date >= monthAgo) buckets.thisMonth.push(s);
      else buckets.older.push(s);
    }

    const groups: SessionGroup[] = [];
    if (pinned.length) groups.push({ label: "Pinned", sessions: pinned });
    if (buckets.today.length)
      groups.push({ label: "Today", sessions: buckets.today });
    if (buckets.yesterday.length)
      groups.push({ label: "Yesterday", sessions: buckets.yesterday });
    if (buckets.thisWeek.length)
      groups.push({ label: "This Week", sessions: buckets.thisWeek });
    if (buckets.thisMonth.length)
      groups.push({ label: "This Month", sessions: buckets.thisMonth });
    if (buckets.older.length)
      groups.push({ label: "Older", sessions: buckets.older });
    return groups;
  }, [sessions]);

  const loadSessions = useSessionStore((s) => s.loadSessions);
  const deleteSessionFn = useSessionStore((s) => s.deleteSession);
  const renameSessionFn = useSessionStore((s) => s.renameSession);
  const pinSessionFn = useSessionStore((s) => s.pinSession);
  const setSearchQueryFn = useSessionStore((s) => s.setSearchQuery);
  const setActiveSession = useChatStore((s) => s.setActiveSession);

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const selectSession = useCallback(
    (id: string) => {
      setActiveSession(id);
    },
    [setActiveSession],
  );

  const createSession = useCallback(async () => {
    // Just clear active session to show welcome page
    // Actual session creation happens on first message send
    setActiveSession(null);
    return "";
  }, [setActiveSession]);

  const deleteSession = useCallback(
    async (id: string) => {
      await deleteSessionFn(id);
      // If deleted session was active, clear it
      if (activeSessionId === id) {
        const remaining = useSessionStore.getState().sessions;
        setActiveSession(remaining.length > 0 ? remaining[0].id : null);
      }
    },
    [deleteSessionFn, activeSessionId, setActiveSession],
  );

  const renameSession = useCallback(
    async (id: string, name: string) => {
      await renameSessionFn(id, name);
    },
    [renameSessionFn],
  );

  const pinSession = useCallback(
    async (id: string, pinned: boolean) => {
      await pinSessionFn(id, pinned);
    },
    [pinSessionFn],
  );

  const setSearchQuery = useCallback(
    (query: string) => {
      setSearchQueryFn(query);
    },
    [setSearchQueryFn],
  );

  const refresh = useCallback(async () => {
    await loadSessions();
  }, [loadSessions]);

  return {
    sessions,
    groupedSessions,
    loading,
    activeSessionId,
    searchQuery,
    selectSession,
    createSession,
    deleteSession,
    renameSession,
    pinSession,
    setSearchQuery,
    refresh,
  };
}
