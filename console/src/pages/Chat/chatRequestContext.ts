export interface QueuedChatRequestData {
  session_id?: unknown;
  user_id?: unknown;
  channel?: unknown;
  agent_id?: unknown;
}

export interface ChatSessionInfo {
  session_id?: string;
  user_id?: string;
  channel?: string;
}

export interface ChatSessionIdentity {
  sessionId: string;
  userId: string;
  channel: string;
}

export interface ChatRequestContext {
  sessionId: string;
  userId: string;
  channel: string;
  agentId: string;
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function resolveChatRequestContext({
  data,
  session,
  selectedAgent,
  getSessionIdentity,
  defaultUserId,
  defaultChannel,
}: {
  data: QueuedChatRequestData;
  session: ChatSessionInfo;
  selectedAgent: string;
  getSessionIdentity: (sessionId?: string) => ChatSessionIdentity;
  defaultUserId: string;
  defaultChannel: string;
}): ChatRequestContext {
  const explicitSessionId =
    nonEmptyString(data.session_id) || nonEmptyString(session.session_id);
  const identity = getSessionIdentity(explicitSessionId);

  return {
    sessionId:
      nonEmptyString(data.session_id) ||
      identity.sessionId ||
      nonEmptyString(session.session_id) ||
      "",
    userId:
      nonEmptyString(data.user_id) ||
      identity.userId ||
      nonEmptyString(session.user_id) ||
      defaultUserId,
    channel:
      nonEmptyString(data.channel) ||
      identity.channel ||
      nonEmptyString(session.channel) ||
      defaultChannel,
    agentId: nonEmptyString(data.agent_id) || selectedAgent,
  };
}
