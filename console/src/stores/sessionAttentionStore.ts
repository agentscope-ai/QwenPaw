import { create } from "zustand";
import { persist } from "zustand/middleware";

const STORAGE_KEY = "qwenpaw-session-attention";

export interface AttentionSession {
  id: string;
  realId?: string;
  lastFinishedAt?: string | null;
}

interface SessionAttentionState {
  seenFinishedAt: Record<string, string | null>;
  initializeSessions: (agentId: string, sessions: AttentionSession[]) => void;
  markSeen: (agentId: string, session: AttentionSession) => void;
}

export function sessionAttentionKey(
  agentId: string,
  session: AttentionSession,
): string {
  return `${agentId}:${session.realId || session.id}`;
}

export function hasUnseenCompletion(
  seenFinishedAt: Record<string, string | null>,
  agentId: string,
  session: AttentionSession,
): boolean {
  if (!session.lastFinishedAt) return false;
  const key = sessionAttentionKey(agentId, session);
  if (!Object.prototype.hasOwnProperty.call(seenFinishedAt, key)) return false;
  const seenAt = seenFinishedAt[key];
  if (!seenAt) return true;
  const finishedMs = Date.parse(session.lastFinishedAt);
  const seenMs = Date.parse(seenAt);
  return (
    Number.isFinite(finishedMs) &&
    Number.isFinite(seenMs) &&
    finishedMs > seenMs
  );
}

export const useSessionAttentionStore = create<SessionAttentionState>()(
  persist(
    (set) => ({
      seenFinishedAt: {},

      initializeSessions: (agentId, sessions) =>
        set((state) => {
          let changed = false;
          const next = { ...state.seenFinishedAt };
          for (const session of sessions) {
            const key = sessionAttentionKey(agentId, session);
            if (!Object.prototype.hasOwnProperty.call(next, key)) {
              // Existing completions are the baseline when this feature first
              // sees a session, so an upgrade does not mark all history unread.
              next[key] = session.lastFinishedAt ?? null;
              changed = true;
            }
          }
          return changed ? { seenFinishedAt: next } : state;
        }),

      markSeen: (agentId, session) => {
        if (!session.lastFinishedAt) return;
        const key = sessionAttentionKey(agentId, session);
        set((state) => {
          if (state.seenFinishedAt[key] === session.lastFinishedAt)
            return state;
          return {
            seenFinishedAt: {
              ...state.seenFinishedAt,
              [key]: session.lastFinishedAt ?? null,
            },
          };
        });
      },
    }),
    {
      name: STORAGE_KEY,
      partialize: (state) => ({ seenFinishedAt: state.seenFinishedAt }),
    },
  ),
);
