export type WorkbenchCapabilityId = "files" | "changes" | "terminal" | "tools";

export interface WorkbenchLayout {
  openTabs: WorkbenchCapabilityId[];
  activeTab: WorkbenchCapabilityId | null;
}

const LAYOUT_STORAGE_PREFIX = "qwenpaw-workbench-layout";
const WIDTH_STORAGE_PREFIX = "qwenpaw-workbench-width";
const CAPABILITY_IDS: WorkbenchCapabilityId[] = [
  "files",
  "changes",
  "terminal",
  "tools",
];

export const EMPTY_WORKBENCH_LAYOUT: WorkbenchLayout = {
  openTabs: [],
  activeTab: null,
};

function isCapabilityId(value: unknown): value is WorkbenchCapabilityId {
  return CAPABILITY_IDS.includes(value as WorkbenchCapabilityId);
}

export function workbenchLayoutStorageKey(
  agentId: string,
  sessionId: string,
): string {
  return `${LAYOUT_STORAGE_PREFIX}:${agentId}:${sessionId}`;
}

export function workbenchWidthStorageKey(
  agentId: string,
  sessionId: string,
): string {
  return `${WIDTH_STORAGE_PREFIX}:${agentId}:${sessionId}`;
}

export function readStoredWorkbenchLayout(storageKey: string): WorkbenchLayout {
  if (typeof window === "undefined") return EMPTY_WORKBENCH_LAYOUT;
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) ?? "null");
    if (!parsed || !Array.isArray(parsed.openTabs)) {
      return EMPTY_WORKBENCH_LAYOUT;
    }
    const openTabs = parsed.openTabs.filter(
      (value: unknown, index: number, values: unknown[]) =>
        isCapabilityId(value) && values.indexOf(value) === index,
    ) as WorkbenchCapabilityId[];
    const activeTab = isCapabilityId(parsed.activeTab)
      ? parsed.activeTab
      : null;
    return {
      openTabs,
      activeTab: activeTab && openTabs.includes(activeTab) ? activeTab : null,
    };
  } catch {
    return EMPTY_WORKBENCH_LAYOUT;
  }
}

export function storeWorkbenchLayout(
  storageKey: string,
  layout: WorkbenchLayout,
): void {
  localStorage.setItem(storageKey, JSON.stringify(layout));
}

export function migrateWorkbenchPreferences(
  agentId: string,
  fromSessionId: string,
  toSessionId: string,
): void {
  if (typeof window === "undefined" || fromSessionId === toSessionId) return;

  const keyFactories = [workbenchLayoutStorageKey, workbenchWidthStorageKey];
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
