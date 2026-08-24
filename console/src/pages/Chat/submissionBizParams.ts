export interface ConsoleBizParams extends Record<string, unknown> {
  session_id: string;
  request_context?: Record<string, unknown>;
  user_prompt_params?: Record<string, string>;
}

export function buildSubmissionBizParams(
  sessionId: string,
  context?: Record<string, unknown>,
): ConsoleBizParams {
  return {
    session_id: sessionId,
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

export function enforceSubmissionSessionId(
  payload: Record<string, unknown>,
  bizParams: Record<string, unknown> | undefined,
  fallbackSessionId: string,
): Record<string, unknown> {
  return {
    ...payload,
    session_id: getSubmissionSessionId(bizParams, fallbackSessionId),
  };
}
