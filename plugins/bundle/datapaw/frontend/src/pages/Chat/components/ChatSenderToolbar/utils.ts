import sessionApi from "../../sessionApi";

type ChatWindow = Window & { currentSessionId?: string };

/** Resolve the backend session id from chat runtime state. */
export function resolveBackendSessionId(
  currentSessionId?: string | null,
): string | null {
  const chatWindow = window as ChatWindow;
  return (
    (currentSessionId && sessionApi.getRealIdForSession(currentSessionId)) ||
    currentSessionId ||
    chatWindow.currentSessionId ||
    null
  );
}

/** Session key for persisting per-session UI preferences. */
export function resolveSessionStorageKey(
  currentSessionId?: string | null,
): string {
  return resolveBackendSessionId(currentSessionId) || "default";
}
