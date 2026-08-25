export interface ConsoleBizParams extends Record<string, unknown> {
  session_id: string;
  user_id: string;
  channel: string;
  request_context?: Record<string, unknown>;
  user_prompt_params?: Record<string, string>;
}

export interface SubmissionIdentity {
  sessionId: string;
  userId: string;
  channel: string;
}

export interface SubmissionContextIdentity {
  agentId: string;
  chatId: string;
  sdkSessionId: string;
}

export interface QueueSubmissionTarget {
  agentId: string;
  conversationReference: string;
  identity: SubmissionIdentity;
}

export function buildSubmissionBizParams(
  identity: SubmissionIdentity,
  context?: Record<string, unknown>,
): ConsoleBizParams {
  return {
    session_id: identity.sessionId,
    user_id: identity.userId,
    channel: identity.channel,
    ...(context ? { request_context: context } : {}),
  };
}

/**
 * Replace a placeholder submission identity once the SDK has created the
 * local session. Non-identity business parameters remain unchanged.
 */
export function rebindSubmissionBizParams(
  bizParams: Record<string, unknown> | undefined,
  identity: SubmissionIdentity,
  contextIdentity: SubmissionContextIdentity,
): ConsoleBizParams {
  const requestContext =
    bizParams?.request_context && typeof bizParams.request_context === "object"
      ? (bizParams.request_context as Record<string, unknown>)
      : {};
  return {
    ...bizParams,
    session_id: identity.sessionId,
    user_id: identity.userId,
    channel: identity.channel,
    request_context: {
      ...requestContext,
      agent_id: contextIdentity.agentId,
      chat_id: contextIdentity.chatId,
      sdk_session_id: contextIdentity.sdkSessionId,
    },
  };
}

export function getSubmissionSessionId(
  bizParams: Record<string, unknown> | undefined,
  fallbackSessionId: string,
): string {
  const frozenSessionId = bizParams?.session_id;
  return typeof frozenSessionId === "string" && frozenSessionId
    ? frozenSessionId
    : fallbackSessionId;
}

export function getSubmissionChatId(
  bizParams: Record<string, unknown> | undefined,
): string | undefined {
  const requestContext = bizParams?.request_context;
  if (!requestContext || typeof requestContext !== "object") return undefined;
  const chatId = (requestContext as Record<string, unknown>).chat_id;
  return typeof chatId === "string" && chatId ? chatId : undefined;
}

export function getSubmissionSdkSessionId(
  bizParams: Record<string, unknown> | undefined,
): string | undefined {
  const requestContext = bizParams?.request_context;
  if (!requestContext || typeof requestContext !== "object") return undefined;
  const sdkSessionId = (requestContext as Record<string, unknown>)
    .sdk_session_id;
  return typeof sdkSessionId === "string" && sdkSessionId
    ? sdkSessionId
    : undefined;
}

export function getSubmissionAgentId(
  bizParams: Record<string, unknown> | undefined,
): string | undefined {
  const requestContext = bizParams?.request_context;
  if (!requestContext || typeof requestContext !== "object") return undefined;
  const agentId = (requestContext as Record<string, unknown>).agent_id;
  return typeof agentId === "string" && agentId ? agentId : undefined;
}

/**
 * Resolve the conversation reference owned by this request. Never falls back
 * to mutable page state, which may already belong to another agent/session.
 */
export function getSubmissionConversationReference(
  bizParams: Record<string, unknown> | undefined,
  fallbackSdkSessionId?: string,
): string | undefined {
  const chatId = getSubmissionChatId(bizParams);
  if (chatId && chatId !== "new") return chatId;
  const sdkSessionId =
    getSubmissionSdkSessionId(bizParams) || fallbackSdkSessionId;
  return sdkSessionId && sdkSessionId !== "new" ? sdkSessionId : undefined;
}

/** Guard submissions while the selected agent and route are changing. */
export function isSubmissionTargetReady(
  bizParams: Record<string, unknown> | undefined,
  selectedAgent: string,
  routeChatId: string | null | undefined,
  resolvedRouteSessionId: string,
): boolean {
  const frozenAgentId = getSubmissionAgentId(bizParams);
  if (frozenAgentId && frozenAgentId !== selectedAgent) return false;

  const frozenChatId = getSubmissionChatId(bizParams);
  if (
    frozenChatId &&
    frozenChatId !== "new" &&
    routeChatId &&
    frozenChatId !== routeChatId
  ) {
    return false;
  }

  const frozenSessionId = getSubmissionSessionId(bizParams, "");
  if (frozenAgentId && frozenChatId && frozenSessionId) return true;

  return !routeChatId || routeChatId === "new" || !!resolvedRouteSessionId;
}

/** Resolve and validate the immutable target carried by one queue item. */
export function getQueueSubmissionTarget(
  bizParams: Record<string, unknown> | undefined,
  itemAgentId: string,
): QueueSubmissionTarget | undefined {
  const frozenAgentId = getSubmissionAgentId(bizParams);
  const conversationReference = getSubmissionConversationReference(bizParams);
  const identity = getSubmissionIdentity(bizParams, {
    sessionId: "",
    userId: "",
    channel: "",
  });
  if (
    !frozenAgentId ||
    frozenAgentId !== itemAgentId ||
    !conversationReference ||
    !identity.sessionId ||
    !identity.userId ||
    !identity.channel
  ) {
    return undefined;
  }
  return {
    agentId: frozenAgentId,
    conversationReference,
    identity,
  };
}

export function getSubmissionIdentity(
  bizParams: Record<string, unknown> | undefined,
  fallback: SubmissionIdentity,
): SubmissionIdentity {
  const sessionId = getSubmissionSessionId(bizParams, fallback.sessionId);
  const userId = bizParams?.user_id;
  const channel = bizParams?.channel;
  return {
    sessionId,
    userId: typeof userId === "string" && userId ? userId : fallback.userId,
    channel:
      typeof channel === "string" && channel ? channel : fallback.channel,
  };
}

export function enforceSubmissionIdentity(
  payload: Record<string, unknown>,
  bizParams: Record<string, unknown> | undefined,
  fallback: SubmissionIdentity,
): Record<string, unknown> {
  const identity = getSubmissionIdentity(bizParams, fallback);
  return {
    ...payload,
    session_id: identity.sessionId,
    user_id: identity.userId,
    channel: identity.channel,
  };
}
