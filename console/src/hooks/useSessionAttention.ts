import { useCallback, useEffect, useMemo } from "react";
import {
  hasUnseenCompletion,
  useSessionAttentionStore,
  type AttentionSession,
} from "../stores/sessionAttentionStore";

function matchesCurrentSession(
  session: AttentionSession,
  currentSessionId: string,
): boolean {
  return session.id === currentSessionId || session.realId === currentSessionId;
}

export function useSessionAttention(
  agentId: string,
  sessions: AttentionSession[],
  currentSessionId: string | undefined,
): ReadonlySet<string> {
  const seenFinishedAt = useSessionAttentionStore(
    (state) => state.seenFinishedAt,
  );
  const initializeSessions = useSessionAttentionStore(
    (state) => state.initializeSessions,
  );
  const markSeen = useSessionAttentionStore((state) => state.markSeen);

  useEffect(() => {
    initializeSessions(agentId, sessions);
  }, [agentId, initializeSessions, sessions]);

  const markCurrentSeen = useCallback(() => {
    if (!currentSessionId || document.visibilityState !== "visible") return;
    const current = sessions.find((session) =>
      matchesCurrentSession(session, currentSessionId),
    );
    if (current) markSeen(agentId, current);
  }, [agentId, currentSessionId, markSeen, sessions]);

  useEffect(() => {
    markCurrentSeen();
    document.addEventListener("visibilitychange", markCurrentSeen);
    return () =>
      document.removeEventListener("visibilitychange", markCurrentSeen);
  }, [markCurrentSeen]);

  return useMemo(() => {
    const unseen = new Set<string>();
    for (const session of sessions) {
      const isVisibleCurrentSession =
        !!currentSessionId &&
        document.visibilityState === "visible" &&
        matchesCurrentSession(session, currentSessionId);
      if (hasUnseenCompletion(seenFinishedAt, agentId, session)) {
        if (!isVisibleCurrentSession) unseen.add(session.id);
      }
    }
    return unseen;
  }, [agentId, currentSessionId, seenFinishedAt, sessions]);
}
