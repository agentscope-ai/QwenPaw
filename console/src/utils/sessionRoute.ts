export function getSessionIdFromPath(pathname: string): string | undefined {
  const match = pathname.match(/^\/chat\/(.+)$/);
  if (!match) return undefined;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

export const CHAT_BASE_PATH = "/chat";

export function buildChatPath(sessionId?: string | null): string {
  return sessionId ? `${CHAT_BASE_PATH}/${sessionId}` : CHAT_BASE_PATH;
}
