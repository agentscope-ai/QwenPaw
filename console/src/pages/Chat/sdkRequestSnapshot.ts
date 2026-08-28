import type { IAgentScopeRuntimeWebUIInputData } from "@agentscope-ai/chat";

export interface ChatSessionIdentity {
  sessionId?: string;
  userId?: string;
  channel?: string;
}

interface LegacyMessageSession {
  session_id?: unknown;
  user_id?: unknown;
  channel?: unknown;
}

export type ChatRequestSnapshotData = Partial<
  Pick<
    IAgentScopeRuntimeWebUIInputData,
    "session_id" | "user_id" | "channel" | "agent_id" | "context"
  >
>;

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value) return value;
  }
  return "";
}

/** Prefer the immutable SDK 1.2 submission snapshot over mutable host state. */
export function resolveChatRequestSnapshot(
  data: ChatRequestSnapshotData,
  fallbackIdentity: ChatSessionIdentity,
  messageSession: LegacyMessageSession,
  fallbackAgentId: string,
) {
  const context = data.context ?? {};
  return {
    sessionId: firstString(
      data.session_id,
      context.session_id,
      fallbackIdentity.sessionId,
      messageSession.session_id,
    ),
    userId: firstString(
      data.user_id,
      context.user_id,
      fallbackIdentity.userId,
      messageSession.user_id,
    ),
    channel: firstString(
      data.channel,
      context.channel,
      fallbackIdentity.channel,
      messageSession.channel,
    ),
    agentId: firstString(data.agent_id, context.agent_id, fallbackAgentId),
    context,
  };
}

export function buildChatSubmissionContext(
  context: Record<string, unknown> | undefined,
  identity: ChatSessionIdentity,
  agentId: string,
): Record<string, unknown> {
  return {
    ...context,
    ...(identity.sessionId ? { session_id: identity.sessionId } : {}),
    ...(identity.userId ? { user_id: identity.userId } : {}),
    ...(identity.channel ? { channel: identity.channel } : {}),
    ...(agentId ? { agent_id: agentId } : {}),
  };
}
