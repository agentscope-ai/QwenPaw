const SESSION_MODEL_CHANGED_EVENT = "session-model-changed";

export interface SessionModelEventScope {
  agentId: string;
  sessionId: string;
  chatId?: string | null;
}

export function dispatchSessionModelChanged(
  scope?: SessionModelEventScope,
): void {
  window.dispatchEvent(
    scope
      ? new CustomEvent(SESSION_MODEL_CHANGED_EVENT, { detail: scope })
      : new Event(SESSION_MODEL_CHANGED_EVENT),
  );
}

export function isSessionModelChangedFor(
  event: Event,
  scope: SessionModelEventScope,
): boolean {
  if (!(event instanceof CustomEvent) || !event.detail) return true;

  const detail = event.detail as Partial<SessionModelEventScope>;
  return (
    detail.agentId === scope.agentId &&
    detail.sessionId === scope.sessionId &&
    (detail.chatId ?? null) === (scope.chatId ?? null)
  );
}
