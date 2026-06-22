import { useCallback, useEffect, useRef, useState } from "react";
import type { IAgentScopeRuntimeWebUIRef } from "@agentscope-ai/chat";
import { extractTextFromMessage } from "../../utils";

export interface UserMessageSnapshot {
  /** Unique message id or generated key */
  id: string;
  /** Extracted plain text from user input */
  text: string;
  /** Unix timestamp (seconds or ms) */
  createdAt?: number;
  /** Index among all user messages in the session */
  index: number;
}

const POLL_INTERVAL_MS = 500;

/**
 * Hook that polls chatRef messages and returns a stable, memoized array
 * of user message snapshots. Only re-renders when the user message count changes.
 */
export function useUserMessageSnapshot(
  chatRef: React.RefObject<IAgentScopeRuntimeWebUIRef | null>,
): { snapshots: UserMessageSnapshot[]; refresh: () => void } {
  const [snapshots, setSnapshots] = useState<UserMessageSnapshot[]>([]);
  const prevCountRef = useRef(0);

  const derive = useCallback(() => {
    const messagesApi = chatRef.current?.messages;
    if (!messagesApi?.getMessages) return;

    const allMessages = messagesApi.getMessages();
    if (!Array.isArray(allMessages)) return;

    const userMessages = allMessages.filter((msg) => msg.role === "user");
    // Only update state when user message count changes
    if (userMessages.length === prevCountRef.current) return;
    prevCountRef.current = userMessages.length;

    const next: UserMessageSnapshot[] = userMessages.map((msg, idx) => {
      const text = extractTextFromMessage(msg);
      const createdAt =
        (msg as any)?.cards?.[0]?.data?.created_at ??
        (msg as any)?.created_at ??
        undefined;
      return {
        id: (msg as any).id || `user-msg-${idx}`,
        text,
        createdAt: createdAt as number | undefined,
        index: idx,
      };
    });

    setSnapshots(next);
  }, [chatRef]);

  // Polling interval
  useEffect(() => {
    derive(); // initial sync
    const timer = setInterval(derive, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [derive]);

  return { snapshots, refresh: derive };
}
