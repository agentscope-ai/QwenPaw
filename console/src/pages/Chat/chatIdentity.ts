export function resolveStopChatId(
  sessionId: string,
  resolveRealId: (sessionId: string) => string | null | undefined,
): string {
  return resolveRealId(sessionId) ?? sessionId;
}
