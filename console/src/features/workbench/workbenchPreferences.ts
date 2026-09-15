export type WorkbenchTab = "files" | "changes" | "terminal" | "tools";

const TAB_STORAGE_PREFIX = "qwenpaw-workbench-tab";
const WIDTH_STORAGE_PREFIX = "qwenpaw-workbench-width";

export function workbenchTabStorageKey(
  agentId: string,
  sessionId: string,
): string {
  return `${TAB_STORAGE_PREFIX}:${agentId}:${sessionId}`;
}

export function workbenchWidthStorageKey(
  agentId: string,
  sessionId: string,
): string {
  return `${WIDTH_STORAGE_PREFIX}:${agentId}:${sessionId}`;
}

export function readStoredWorkbenchTab(storageKey: string): WorkbenchTab {
  if (typeof window === "undefined") return "files";
  const value = localStorage.getItem(storageKey);
  return value === "files" ||
    value === "changes" ||
    value === "terminal" ||
    value === "tools"
    ? value
    : "files";
}

export function migrateWorkbenchPreferences(
  agentId: string,
  fromSessionId: string,
  toSessionId: string,
): void {
  if (typeof window === "undefined" || fromSessionId === toSessionId) return;

  const keyFactories = [workbenchTabStorageKey, workbenchWidthStorageKey];
  keyFactories.forEach((createKey) => {
    const sourceKey = createKey(agentId, fromSessionId);
    const targetKey = createKey(agentId, toSessionId);
    const value = localStorage.getItem(sourceKey);
    if (value !== null && localStorage.getItem(targetKey) === null) {
      localStorage.setItem(targetKey, value);
    }
    localStorage.removeItem(sourceKey);
  });
}
