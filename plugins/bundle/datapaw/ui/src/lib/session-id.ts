import {
  isLikelyBackendSessionId,
  sessionIdFromArtifactPath,
} from "@/pages/Chat/lib/taskApiSession";

export function getHostSessionApi(): Record<string, unknown> | null {
  const bridge = (
    window as {
      QwenPaw?: {
        host?: { chatBridge?: { _sessionApi?: Record<string, unknown> } };
      };
    }
  ).QwenPaw?.host?.chatBridge;
  if (bridge?._sessionApi) {
    return bridge._sessionApi;
  }

  const api = (
    window as { QwenPaw?: { modules?: Record<string, Record<string, unknown>> } }
  ).QwenPaw?.modules?.["Chat/sessionApi/index"]?.default;
  return (api as Record<string, unknown>) ?? null;
}

/**
 * Resolve the backend session id required by /api/tasks/{session_id}/…
 * (files, preview, download, etc.).
 */
export function resolveTaskApiSessionId(
  localSessionId?: string | null,
  artifactPath?: string | null,
): string | null {
  const sid =
    localSessionId ||
    (window as Window & { currentSessionId?: string }).currentSessionId ||
    null;

  const api = getHostSessionApi();
  const getRealId = api?.getRealIdForSession;
  if (sid && typeof getRealId === "function") {
    const real = getRealId.call(api, sid) as string | null | undefined;
    if (real) return real;
  }

  if (sid && isLikelyBackendSessionId(sid)) return sid;

  const fromPath = sessionIdFromArtifactPath(artifactPath);
  if (fromPath) return fromPath;

  return sid;
}

/** Resolve backend UUID from host sessionApi when window.currentSessionId is a local id. */
export function resolveBackendSessionId(
  localSessionId?: string | null,
): string | null {
  return resolveTaskApiSessionId(localSessionId);
}
