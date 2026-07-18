import type {
  IAgentScopeRuntimeWebUIOptions,
  IAgentScopeRuntimeWebUISessionAPI,
} from "@agentscope-ai/chat";
import sessionApi from "./sessionApi";

export function buildChatSessionOptions(
  currentSessionId: string | undefined,
  api: IAgentScopeRuntimeWebUISessionAPI = sessionApi,
): IAgentScopeRuntimeWebUIOptions["session"] {
  return {
    multiple: true,
    // Keep the SDK session provider controlled even on the blank /chat route.
    // Omitting this key lets the SDK retain a stale internal currentSessionId.
    currentSessionId,
    hideBuiltInSessionList: true,
    api,
  };
}
