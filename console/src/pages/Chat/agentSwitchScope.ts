export interface PendingAgentChatScope {
  agentId: string;
  chatId?: string;
}

/**
 * Keep the runtime agent and chat ID in the same scope while React Router is
 * applying the target route. Otherwise one render can pair the new agent with
 * the previous agent's chat ID.
 */
export function resolveRuntimeChatId(
  routeChatId: string | undefined,
  runtimeAgent: string,
  pendingScope: PendingAgentChatScope | null,
): string | undefined {
  return pendingScope?.agentId === runtimeAgent
    ? pendingScope.chatId
    : routeChatId;
}

/**
 * Resolve the route consumed by ChatSessionInitializer.
 *
 * A user-initiated blank chat must win over both the current route and an
 * Agent-switch target, otherwise the SDK can immediately select the previous
 * conversation again while React Router is applying `/chat`.
 */
export function resolveSessionInitializerChatId(
  routeChatId: string | undefined,
  runtimeAgent: string,
  pendingScope: PendingAgentChatScope | null,
  isBlankChatPending: boolean,
): string | undefined {
  if (isBlankChatPending) return undefined;
  return resolveRuntimeChatId(routeChatId, runtimeAgent, pendingScope);
}
