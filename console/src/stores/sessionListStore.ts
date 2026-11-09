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
import type { ChatSource } from "../api/types/chat";
import { useAgentStore } from "./agentStore";

export interface ExtendedSession extends IAgentScopeRuntimeWebUISession {
  realId?: string;
  sessionId?: string;
  userId?: string;
  channel?: string;
  createdAt?: string | null;
  updatedAt?: string | null;
  lastFinishedAt?: string | null;
  meta?: Record<string, unknown>;
  status?: string;
  generating?: boolean;
  pinned?: boolean;
  archivedAt?: string | null;
  archived?: boolean;
  source?: ChatSource;
  groupId?: string | null;
  parentSessionId?: string | null;
  rootSessionId?: string | null;
}

interface SessionListStore {
  sessions: ExtendedSession[];
  /** Resolved route metadata, including Chats absent from the sidebar. */
  resolvedRouteSession: ExtendedSession | null;
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

  /** Called after a session CRUD operation to refresh the sidebar. */
  syncSessions: (sessions: ExtendedSession[]) => void;
}

/** Resolve canonical Chat IDs before confirmed, display, or runtime aliases. */
export function findSessionByReference<
  T extends { id: string; realId?: string; sessionId?: string },
>(sessions: readonly T[], id: string, resolved?: T | null): T | undefined {
  const canonical = sessions.find(
    (session) => (session.realId ?? session.id) === id,
  );
  if (canonical) return canonical;

  if (
    resolved?.id === id ||
    resolved?.realId === id ||
    resolved?.sessionId === id
  )
    return resolved;

  const display = sessions.find((session) => session.id === id);
  if (display) return display;

  // Multiple Chats may share a runtime identity; never guess between them.
  const runtimeMatches = new Map<string, T>();
  for (const session of sessions) {
    if (session.sessionId === id)
      runtimeMatches.set(session.realId ?? session.id, session);
  }
  return runtimeMatches.size === 1
    ? runtimeMatches.values().next().value
    : undefined;
}

export const useSessionListStore = create<SessionListStore>((set, get) => ({
  sessions: [],
  resolvedRouteSession: null,
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

// The shared list belongs to one agent at a time. Clear it synchronously on
// every agent change so consumers (e.g. the simple-mode sidebar) never keep
// rendering — and navigating to — the previous agent's sessions while the
// new agent's list is still loading. The library setter stays registered:
// it belongs to the mounted initializer, which re-syncs after the switch.
useAgentStore.subscribe((state, prevState) => {
  if (state.selectedAgent !== prevState.selectedAgent) {
    useSessionListStore.setState({
      sessions: [],
      resolvedRouteSession: null,
      lastUpdated: Date.now(),
    });
  }
});
