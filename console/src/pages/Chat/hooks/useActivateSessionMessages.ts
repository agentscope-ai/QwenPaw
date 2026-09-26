import { useLayoutEffect, type RefObject } from "react";
import type { IAgentScopeRuntimeWebUIRef } from "@agentscope-ai/chat";

/** Activate the selected cache through the SDK's public ref, even on a quick return. */
export function useActivateSessionMessages(
  sessionId: string | undefined,
  sdkRef: RefObject<Pick<IAgentScopeRuntimeWebUIRef, "messages"> | null>,
) {
  useLayoutEffect(() => {
    if (sessionId && sessionId !== "new") {
      sdkRef.current?.messages.setSessionMessages(
        sessionId,
        (cached) => cached,
        { activate: true },
      );
    }
  }, [sessionId, sdkRef]);
}
