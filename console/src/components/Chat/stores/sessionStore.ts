import { create } from "zustand";
import type { ChatSession, SessionGroup } from "../types";
import { chatApi } from "../../../api/modules/chat";
import { DEFAULT_SESSION_NAME, SESSION_STATUS } from "../constants";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SessionState {
  sessions: ChatSession[];
  loading: boolean;
  searchQuery: string;

  // Computed
  pinnedSessions: () => ChatSession[];
  filteredSessions: () => ChatSession[];
  groupedSessions: () => SessionGroup[];

  // Actions
  loadSessions: () => Promise<void>;
  createSession: (userId?: string, channel?: string) => Promise<string>;
  deleteSession: (id: string) => Promise<void>;
  batchDeleteSessions: (ids: string[]) => Promise<void>;
  renameSession: (id: string, name: string) => Promise<void>;
  pinSession: (id: string, pinned: boolean) => Promise<void>;
  setSearchQuery: (query: string) => void;
  updateSessionStatus: (id: string, status: ChatSession["status"]) => void;
  updateSessionLastMessage: (id: string, message: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function groupByDate(sessions: ChatSession[]): SessionGroup[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);
  const monthAgo = new Date(today.getTime() - 30 * 86400000);

  const groups: Record<string, ChatSession[]> = {
    today: [],
    yesterday: [],
    thisWeek: [],
    thisMonth: [],
    older: [],
  };

  for (const session of sessions) {
    const date = new Date(session.updatedAt || session.createdAt);
    if (date >= today) groups.today.push(session);
    else if (date >= yesterday) groups.yesterday.push(session);
    else if (date >= weekAgo) groups.thisWeek.push(session);
    else if (date >= monthAgo) groups.thisMonth.push(session);
    else groups.older.push(session);
  }

  const result: SessionGroup[] = [];
  if (groups.today.length)
    result.push({ label: "Today", sessions: groups.today });
  if (groups.yesterday.length)
    result.push({ label: "Yesterday", sessions: groups.yesterday });
  if (groups.thisWeek.length)
    result.push({ label: "This Week", sessions: groups.thisWeek });
  if (groups.thisMonth.length)
    result.push({ label: "This Month", sessions: groups.thisMonth });
  if (groups.older.length)
    result.push({ label: "Older", sessions: groups.older });
  return result;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  loading: false,
  searchQuery: "",

  pinnedSessions: () => get().sessions.filter((s) => s.pinned),

  filteredSessions: () => {
    const { sessions, searchQuery } = get();
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.lastMessage && s.lastMessage.toLowerCase().includes(q)),
    );
  },

  groupedSessions: () => {
    const pinned = get().pinnedSessions();
    const unpinned = get()
      .filteredSessions()
      .filter((s) => !s.pinned);
    const groups: SessionGroup[] = [];
    if (pinned.length) groups.push({ label: "Pinned", sessions: pinned });
    groups.push(...groupByDate(unpinned));
    return groups;
  },

  loadSessions: async () => {
    set({ loading: true });
    try {
      const chats = await chatApi.listChats();
      const sessions: ChatSession[] = chats
        .filter((c) => c.id && c.id !== "undefined")
        .map((c) => ({
          id: c.id,
          sessionId: c.session_id || "",
          userId: c.user_id || "",
          name: c.name || DEFAULT_SESSION_NAME,
          pinned: c.pinned ?? false,
          status: c.status ?? SESSION_STATUS.IDLE,
          createdAt: c.created_at || new Date().toISOString(),
          updatedAt: c.updated_at || c.created_at || new Date().toISOString(),
          channel: c.channel || undefined,
        }));
      // Sort: pinned first, then by createdAt descending
      sessions.sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        return (
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
        );
      });
      set({ sessions });
    } finally {
      set({ loading: false });
    }
  },

  createSession: async (userId?: string, channel?: string) => {
    const sessionId = Date.now().toString();
    const chatSpec = await chatApi.createChat({
      session_id: sessionId,
      user_id: userId || "default",
      channel: channel || "console",
      name: DEFAULT_SESSION_NAME,
    });
    const newSession: ChatSession = {
      id: chatSpec.id,
      sessionId: chatSpec.session_id || sessionId,
      userId: chatSpec.user_id || "",
      name: chatSpec.name || DEFAULT_SESSION_NAME,
      pinned: false,
      status: SESSION_STATUS.IDLE,
      createdAt: chatSpec.created_at || new Date().toISOString(),
      updatedAt: chatSpec.updated_at || new Date().toISOString(),
    };
    set((state) => ({ sessions: [newSession, ...state.sessions] }));
    return chatSpec.id;
  },

  deleteSession: async (id) => {
    await chatApi.deleteChat(id);
    set((state) => ({
      sessions: state.sessions.filter((s) => s.id !== id),
    }));
  },

  batchDeleteSessions: async (ids) => {
    await chatApi.batchDeleteChats(ids);
    const idSet = new Set(ids);
    set((state) => ({
      sessions: state.sessions.filter((s) => !idSet.has(s.id)),
    }));
  },

  renameSession: async (id, name) => {
    await chatApi.updateChat(id, { name });
    set((state) => ({
      sessions: state.sessions.map((s) => (s.id === id ? { ...s, name } : s)),
    }));
  },

  pinSession: async (id, pinned) => {
    await chatApi.updateChat(id, { pinned });
    set((state) => {
      const updated = state.sessions.map((s) =>
        s.id === id ? { ...s, pinned } : s,
      );
      // Sort: pinned first, then by createdAt descending
      updated.sort((a, b) => {
        if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
        return (
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
        );
      });
      return { sessions: updated };
    });
  },

  setSearchQuery: (query) => set({ searchQuery: query }),

  updateSessionStatus: (id, status) =>
    set((state) => ({
      sessions: state.sessions.map((s) => (s.id === id ? { ...s, status } : s)),
    })),

  updateSessionLastMessage: (id, message) =>
    set((state) => ({
      sessions: state.sessions.map((s) =>
        s.id === id
          ? { ...s, lastMessage: message, updatedAt: new Date().toISOString() }
          : s,
      ),
    })),
}));
