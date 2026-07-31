import type {
  IAgentScopeRuntimeWebUIOptions,
  IAgentScopeRuntimeWebUISessionAPI,
} from "@agentscope-ai/chat";
import sessionApi from "./sessionApi";

/**
 * Resolve the session id owned by the controlled SDK provider.
 *
 * An explicit New Chat navigates to the base `/chat` route before the first
 * request resolves a backend UUID. Keep the prepared local id controlled
 * during that window; passing `undefined` makes the SDK clear its internal
 * current session and then recreate it during submit, which invalidates the
 * just-started request and visibly reloads the message list.
 */
export function resolveControlledSdkSessionId(
  routeSessionId: string | undefined,
): string | undefined {
  // React Router applies navigation one render after SessionApi records the
  // destination. Preserve that destination during the intermediate `/chat`
  // render instead of briefly controlling the SDK with `undefined`.
  const sessionId = routeSessionId || sessionApi.lastActiveChatId || undefined;
  return sessionApi.getLibrarySessionId(sessionId);
}

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
