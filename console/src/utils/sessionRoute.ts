export const CHAT_BASE_PATH = "/chat";

export interface ChatPathParts {
  agentId?: string;
  sessionId?: string;
}

function decodePathSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * Parse `/chat`, `/chat/:sessionId` (legacy), or `/chat/:agentId/:sessionId`.
 */
export function parseChatPath(pathname: string): ChatPathParts {
  const path = pathname.split(/[?#]/, 1)[0] ?? "";
  const two = path.match(/^\/chat\/([^/]+)\/(.+)$/);
  if (two) {
    return {
      agentId: decodePathSegment(two[1]),
      sessionId: decodePathSegment(two[2]),
    };
  }
  const one = path.match(/^\/chat\/(.+)$/);
  if (one) {
    return { sessionId: decodePathSegment(one[1]) };
  }
  return {};
}

export function getSessionIdFromPath(pathname: string): string | undefined {
  return parseChatPath(pathname).sessionId;
}

export function getAgentIdFromPath(pathname: string): string | undefined {
  return parseChatPath(pathname).agentId;
}

export function buildChatPath(
  sessionId?: string | null,
  agentId?: string | null,
): string {
  if (sessionId && agentId) {
    return `${CHAT_BASE_PATH}/${encodeURIComponent(
      agentId,
    )}/${encodeURIComponent(sessionId)}`;
  }
  if (sessionId) {
    return `${CHAT_BASE_PATH}/${encodeURIComponent(sessionId)}`;
  }
  return CHAT_BASE_PATH;
}

/** True when the URL already names this agent's session and must not be replaced. */
export function shouldPreserveUrlSessionOnAgentSwitch(
  urlAgentId: string | undefined,
  selectedAgent: string,
  urlSessionId: string | null | undefined,
): boolean {
  return Boolean(urlAgentId && urlAgentId === selectedAgent && urlSessionId);
}
