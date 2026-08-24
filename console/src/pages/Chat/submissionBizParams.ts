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
