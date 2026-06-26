export const SESSION_UPDATED_EVENT = "qwenpaw:session-updated";
export const SESSION_UPDATED_PUSH_PREFIX = "session_updated:";

export interface SessionUpdatedEventDetail {
  sessionId: string;
}

export function getSessionIdFromPushMessage(text?: string): string | null {
  if (!text?.startsWith(SESSION_UPDATED_PUSH_PREFIX)) return null;
  const sessionId = text.substring(SESSION_UPDATED_PUSH_PREFIX.length);
  return sessionId || null;
}

export function dispatchSessionUpdated(sessionId: string) {
  window.dispatchEvent(
    new CustomEvent<SessionUpdatedEventDetail>(SESSION_UPDATED_EVENT, {
      detail: { sessionId },
    }),
  );
}
