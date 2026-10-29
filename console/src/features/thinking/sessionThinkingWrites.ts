// Submitted writes belong to the chat, not to the lifetime of its settings UI.
const pendingWrites = new Map<string, Promise<void>>();

export function sessionThinkingScope(
  agentId: string,
  sessionId: string,
  chatId?: string | null,
) {
  return JSON.stringify([
    agentId,
    chatId ? "chat" : "session",
    chatId || sessionId,
  ]);
}

export function enqueueSessionThinkingWrite<T>(
  scope: string,
  write: () => Promise<T>,
): Promise<T> {
  const result = (pendingWrites.get(scope) ?? Promise.resolve()).then(write);
  const settled = result.then(
    () => undefined,
    () => undefined,
  );
  pendingWrites.set(scope, settled);
  void settled.then(() => {
    if (pendingWrites.get(scope) === settled) pendingWrites.delete(scope);
  });
  return result;
}

export function waitForSessionThinkingWrites(
  scope: string,
): Promise<void> | undefined {
  let pending = pendingWrites.get(scope);
  if (!pending) return undefined;
  return (async () => {
    do {
      await pending;
    } while ((pending = pendingWrites.get(scope)));
  })();
}
