/**
 * sessionListStore — a thin Zustand bridge that makes the chat library's
 * session list accessible outside the AgentScopeRuntimeWebUI context tree
 * (e.g. the simple-mode sidebar).
 *
 * Write path:  ChatSessionInitializer (inside context) → syncSessionsToStore()
 * Read path:   SidebarSessionList (outside context)    → useSessionListStore()
 * Refresh path: any component can call refreshSessionList() to trigger a
 *               backend fetch and update both the store AND the chat library
 *               context (via the registered setSessions callback).
 */
import { create } from "zustand";
import type { IAgentScopeRuntimeWebUISession } from "@agentscope-ai/chat";

export interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
  realId?: string;
  sessionId?: string;
  userId?: string;
  channel?: string;
  createdAt?: string | null;
  updatedAt?: string | null;
  meta?: Record<string, unknown>;
  status?: string;
  generating?: boolean;
  pinned?: boolean;
}

interface SessionListStore {
  sessions: ExtendedSession[];
  /** Timestamp of last update — used to detect staleness */
  lastUpdated: number;
  /**
   * Registered by ChatSessionInitializer to propagate changes back into
   * the chat library's own context state.
   */
  _setLibrarySessions: ((sessions: ExtendedSession[]) => void) | null;

  /** Called by ChatSessionInitializer whenever the library's sessions change */
  syncFromLibrary: (
    sessions: ExtendedSession[],
    setLibrarySessions: (s: ExtendedSession[]) => void,
  ) => void;

  /** Called by anyone (sidebar, drawer) after a CRUD operation */
  syncSessions: (sessions: ExtendedSession[]) => void;
}

export const useSessionListStore = create<SessionListStore>((set, get) => ({
  sessions: [],
  lastUpdated: 0,
  _setLibrarySessions: null,

  syncFromLibrary: (sessions, setLibrarySessions) => {
    set({
      sessions,
      lastUpdated: Date.now(),
      _setLibrarySessions: setLibrarySessions,
    });
  },

  syncSessions: (sessions) => {
    // Update Zustand store
    set({ sessions, lastUpdated: Date.now() });
    // Propagate back into the chat library context
    get()._setLibrarySessions?.(sessions);
  },
}));

/**
 * Convenience: update both the Zustand store and the chat library context.
 * Call this after any CRUD that produces a fresh session list.
 */
export function syncSessionsGlobal(sessions: ExtendedSession[]) {
  useSessionListStore.getState().syncSessions(sessions);
}
