import sessionApi from "../pages/Chat/sessionApi";

function mapIfKnown(raw: string, requireKnownInList: boolean): string {
  if (!raw) return "";
  const mapped = sessionApi.getBackendSessionId(raw);
  if (!mapped) return "";
  if (!requireKnownInList) return mapped;
  // Same readiness check as Chat bg-task hydration: mapping alone is not
  // enough when the id is still an unresolved local timestamp.
  const knownInList =
    mapped !== raw || sessionApi.getRealIdForSession(raw) != null;
  return knownInList ? mapped : "";
}

/**
 * Resolve a backend-compatible session_id for tool-call APIs.
 *
 * Align with Chat hydration / getSessionIdentity:
 * 1. explicit preferred id (tool card / caller)
 * 2. lastActiveChatId (intentional selection; do not prefer window)
 * 3. window.currentSessionId only when it still resolves in the session list
 *
 * Always map through sessionApi so local-timestamp library ids become the
 * coordinator's session_id.
 */
export function resolveBackendSessionId(preferred?: string | null): string {
  const preferredTrim = (preferred && preferred.trim()) || "";
  if (preferredTrim) {
    // Explicit caller id: map even if list membership is still catching up.
    return (
      mapIfKnown(preferredTrim, false) ||
      sessionApi.getBackendSessionId(preferredTrim)
    );
  }

  const fromActive = mapIfKnown(sessionApi.lastActiveChatId || "", true);
  if (fromActive) return fromActive;

  // Soft fallback while a brand-new chat is still joining the list.
  const activeRaw = sessionApi.lastActiveChatId || "";
  if (activeRaw) {
    return sessionApi.getBackendSessionId(activeRaw);
  }

  const windowSid =
    (window as unknown as { currentSessionId?: string }).currentSessionId ?? "";
  return mapIfKnown(windowSid, true);
}
