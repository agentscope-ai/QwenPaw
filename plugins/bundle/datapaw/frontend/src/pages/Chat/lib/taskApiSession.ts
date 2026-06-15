import sessionApi from "../sessionApi";

/** Backend session ids are numeric timestamps (e.g. 1781330102407). */
export function isLikelyBackendSessionId(id: string): boolean {
  return /^\d{10,}$/.test(id);
}

/** Artifact paths are `{session_id}/{graph_id}/{node_id}/...`. */
export function sessionIdFromArtifactPath(
  filepath?: string | null,
): string | null {
  if (!filepath) return null;
  const first = filepath.split("/").filter(Boolean)[0];
  if (!first) return null;
  return isLikelyBackendSessionId(first) ? first : null;
}

/**
 * Resolve the backend session id required by /api/tasks/{session_id}/…
 * (files, preview, download, etc.). Never pass chat UUID when a real id exists.
 */
export function resolveTaskApiSessionId(
  localSessionId?: string | null,
  artifactPath?: string | null,
): string | null {
  const chatWindow = window as Window & { currentSessionId?: string };
  const candidates = [
    localSessionId,
    chatWindow.currentSessionId,
  ].filter(Boolean) as string[];

  for (const sid of candidates) {
    const real = sessionApi.getRealIdForSession(sid);
    if (real) return real;
    if (isLikelyBackendSessionId(sid)) return sid;
  }

  const fromPath = sessionIdFromArtifactPath(artifactPath);
  if (fromPath) return fromPath;

  return candidates[0] ?? null;
}
