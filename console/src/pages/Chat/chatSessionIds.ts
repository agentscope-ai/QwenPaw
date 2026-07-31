export const DEFAULT_QUEUE_AGENT_ID = "__default_agent__";
export const QUEUE_AGENT_SEPARATOR = "::";

export function stripQueueAgentPrefix(sessionId?: string) {
  if (!sessionId) return "";
  const separatorIndex = sessionId.indexOf(QUEUE_AGENT_SEPARATOR);
  return separatorIndex >= 0
    ? sessionId.slice(separatorIndex + QUEUE_AGENT_SEPARATOR.length)
    : sessionId;
}

export function getQueueAgentId(sessionId?: string) {
  if (!sessionId) return undefined;
  const separatorIndex = sessionId.indexOf(QUEUE_AGENT_SEPARATOR);
  if (separatorIndex < 0) return undefined;
  const agentId = sessionId.slice(0, separatorIndex);
  return agentId && agentId !== DEFAULT_QUEUE_AGENT_ID ? agentId : undefined;
}

export function resolveBackendChatSessionId(
  sessionId: string | undefined,
  getBackendSessionId: (sessionId: string) => string,
) {
  const rawSessionId = stripQueueAgentPrefix(sessionId);
  return rawSessionId ? getBackendSessionId(rawSessionId) : "";
}

export function buildAgentScopedQueueSessionId(
  sessionId: string,
  agentId: string | undefined,
) {
  return `${
    agentId || DEFAULT_QUEUE_AGENT_ID
  }${QUEUE_AGENT_SEPARATOR}${sessionId}`;
}

export function resolveAgentScopedQueueSessionId(
  sessionId: string | undefined,
  agentId: string | undefined,
  getQueueSessionId: (sessionId: string) => string,
) {
  if (!sessionId) return undefined;
  if (sessionId.includes(QUEUE_AGENT_SEPARATOR)) return sessionId;

  const rawSessionId = stripQueueAgentPrefix(sessionId);
  const queueSessionId = rawSessionId ? getQueueSessionId(rawSessionId) : "";
  return buildAgentScopedQueueSessionId(queueSessionId || sessionId, agentId);
}
