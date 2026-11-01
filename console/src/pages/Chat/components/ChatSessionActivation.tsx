import { useEffect, type RefObject } from "react";
import {
  useChatAnywhereSessionsState,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";
import type { createSdkSessionAdapter } from "../sdkSessionAdapter";

/** Activate cached messages only after the SDK has adopted the route. */
export function ChatSessionActivation({
  sessionId,
  sdkRef,
  adapter,
}: {
  sessionId?: string;
  sdkRef: RefObject<Pick<IAgentScopeRuntimeWebUIRef, "messages"> | null>;
  adapter?: ReturnType<typeof createSdkSessionAdapter>;
}) {
  const { currentSessionId } = useChatAnywhereSessionsState();
  useEffect(() => {
    if (sessionId && sessionId !== "new" && currentSessionId === sessionId) {
      const messages = sdkRef.current?.messages;
      if (!messages) return;
      // Archived Chats may be absent from the SDK list, so it cannot bridge
      // a loaded runtime alias to the canonical route's message cache itself.
      const cacheId = adapter?.getMessageCacheId(sessionId) ?? sessionId;
      messages.setSessionMessages(
        sessionId,
        cacheId === sessionId
          ? (cached) => cached
          : messages.getSessionMessages(cacheId),
        { activate: true },
      );
    }
  }, [currentSessionId, sessionId, sdkRef, adapter]);
  return null;
}
