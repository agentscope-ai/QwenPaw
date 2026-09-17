import { useEffect, useRef } from "react";
import { resolveChatGroupId } from "../utils/chatGroups";

interface RevealableChat {
  id?: string;
  realId?: string;
  source?: "chat" | "cron" | "subagent";
  groupId?: string | null;
}

export function useRevealActiveChatGroup(
  currentSessionId: string | undefined,
  sessions: RevealableChat[],
  expandGroup: (groupId: string) => void,
): void {
  const revealedSessionRef = useRef<string | null>(null);

  useEffect(() => {
    if (!currentSessionId) {
      revealedSessionRef.current = null;
      return;
    }
    if (revealedSessionRef.current === currentSessionId) return;

    const active = sessions.find(
      (session) =>
        session.id === currentSessionId || session.realId === currentSessionId,
    );
    if (!active) return;

    revealedSessionRef.current = currentSessionId;
    expandGroup(resolveChatGroupId(active));
  }, [currentSessionId, expandGroup, sessions]);
}
