import { useEffect, type RefObject } from "react";
import {
  useChatAnywhereSessionsState,
  type IAgentScopeRuntimeWebUIRef,
} from "@agentscope-ai/chat";

/** Activate cached messages only after the SDK has adopted the route. */
export function ChatSessionActivation({
  sessionId,
  sdkRef,
}: {
  sessionId?: string;
  sdkRef: RefObject<Pick<IAgentScopeRuntimeWebUIRef, "messages"> | null>;
}) {
  const { currentSessionId } = useChatAnywhereSessionsState();
  useEffect(() => {
    if (sessionId && sessionId !== "new" && currentSessionId === sessionId) {
      sdkRef.current?.messages.setSessionMessages(
        sessionId,
        (cached) => cached,
        { activate: true },
      );
    }
  }, [currentSessionId, sessionId, sdkRef]);
  return null;
}
