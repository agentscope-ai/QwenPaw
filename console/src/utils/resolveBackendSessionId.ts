import sessionApi from "../pages/Chat/sessionApi";

/**
 * Resolve a backend-compatible session_id for tool-call APIs.
 *
 * These APIs VALIDATE the session_id against the running entry and return
 * 404 on mismatch, so an unknown/stale id must never leak through. Every
 * branch therefore resolves strictly and yields "" when the mapping cannot
 * be confirmed — callers (useToolCallControl / useBackgroundTaskWatcher)
 * treat "" as "not ready yet" and retry with backoff while the session
 * list catches up.
 *
 * Lookup order:
 * 1. explicit preferred id (tool card / caller)
 * 2. lastActiveChatId (intentional selection; do not prefer window)
 * 3. window.currentSessionId
 */
export function resolveBackendSessionId(preferred?: string | null): string {
  const preferredTrim = (preferred && preferred.trim()) || "";
  if (preferredTrim) {
    return sessionApi.getBackendSessionIdStrict(preferredTrim);
  }

  const fromActive = sessionApi.getBackendSessionIdStrict(
    sessionApi.lastActiveChatId || "",
  );
  if (fromActive) return fromActive;

  const windowSid =
    (window as unknown as { currentSessionId?: string }).currentSessionId ??
    "";
  return sessionApi.getBackendSessionIdStrict(windowSid);
}
