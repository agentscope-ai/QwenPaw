const KEY_PREFIX = "qwenpaw-pending-project-dir:";

export function getPendingProjectDirectory(agentId: string): string | null {
  return sessionStorage.getItem(`${KEY_PREFIX}${agentId}`);
}

export function setPendingProjectDirectory(
  agentId: string,
  path: string | null,
): void {
  const key = `${KEY_PREFIX}${agentId}`;
  if (path) {
    sessionStorage.setItem(key, path);
  } else {
    sessionStorage.removeItem(key);
  }
}
