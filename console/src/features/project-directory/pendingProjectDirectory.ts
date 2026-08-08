const KEY_PREFIX = "qwenpaw-session-project-dir:";

function storageKey(agentId: string, sessionId: string): string {
  return `${KEY_PREFIX}${agentId}:${sessionId}`;
}

export function getPendingProjectDirectory(
  agentId: string,
  sessionId: string,
): string | null {
  return sessionStorage.getItem(storageKey(agentId, sessionId));
}

export function setPendingProjectDirectory(
  agentId: string,
  sessionId: string,
  path: string | null,
): void {
  const key = storageKey(agentId, sessionId);
  if (path) {
    sessionStorage.setItem(key, path);
  } else {
    sessionStorage.removeItem(key);
  }
}

export function migratePendingProjectDirectory(
  agentId: string,
  fromSessionId: string,
  toSessionId: string,
): void {
  if (fromSessionId === toSessionId) return;
  const path = getPendingProjectDirectory(agentId, fromSessionId);
  if (!path) return;
  setPendingProjectDirectory(agentId, toSessionId, path);
  setPendingProjectDirectory(agentId, fromSessionId, null);
}

export function withPendingProjectDirectory(
  requestBody: Record<string, unknown>,
  agentId: string,
  sessionId: string,
): {
  requestBody: Record<string, unknown>;
  projectDir: string | null;
} {
  const projectDir = getPendingProjectDirectory(agentId, sessionId);
  if (!projectDir) return { requestBody, projectDir: null };
  const currentContext =
    requestBody.request_context &&
    typeof requestBody.request_context === "object"
      ? (requestBody.request_context as Record<string, unknown>)
      : {};
  return {
    requestBody: {
      ...requestBody,
      request_context: {
        ...currentContext,
        session_project_dir: projectDir,
      },
    },
    projectDir,
  };
}
