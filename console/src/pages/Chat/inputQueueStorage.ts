const INPUT_QUEUE_STORAGE_PREFIX = "agentscope-runtime-webui-input-queue";
const INPUT_QUEUE_CHANNEL_NAME = "agentscope-runtime-webui-input-queue";

interface PersistedInputQueueState {
  items: Array<{ id?: string; [key: string]: unknown }>;
  paused: boolean;
  ownerTabId?: string;
  ownerUpdatedAt?: number;
  command?: unknown;
  updatedAt: number;
  [key: string]: unknown;
}

function getInputQueueStorageKey(sessionId: string) {
  return `${INPUT_QUEUE_STORAGE_PREFIX}:${sessionId}`;
}

function createEmptyState(now = Date.now()): PersistedInputQueueState {
  return {
    items: [],
    paused: false,
    updatedAt: now,
  };
}

function normalizeState(
  state?: Partial<PersistedInputQueueState> | null,
  now = Date.now(),
): PersistedInputQueueState {
  return {
    ...state,
    items: Array.isArray(state?.items) ? state.items : [],
    paused: !!state?.paused,
    ownerTabId: state?.ownerTabId,
    ownerUpdatedAt: state?.ownerUpdatedAt,
    command: state?.command,
    updatedAt: state?.updatedAt ?? now,
  };
}

function isEmptyState(state: PersistedInputQueueState) {
  return state.items.length === 0 && !state.command;
}

function readState(sessionId: string): PersistedInputQueueState {
  if (typeof localStorage === "undefined") return createEmptyState();

  try {
    const raw = localStorage.getItem(getInputQueueStorageKey(sessionId));
    return normalizeState(raw ? JSON.parse(raw) : undefined);
  } catch {
    return createEmptyState();
  }
}

function writeState(sessionId: string, state: PersistedInputQueueState) {
  if (typeof localStorage === "undefined") return;

  const key = getInputQueueStorageKey(sessionId);
  if (isEmptyState(state)) {
    localStorage.removeItem(key);
    return;
  }

  localStorage.setItem(key, JSON.stringify(state));
}

function removeState(sessionId: string) {
  if (typeof localStorage === "undefined") return;
  localStorage.removeItem(getInputQueueStorageKey(sessionId));
}

function broadcastState(sessionId: string, state: PersistedInputQueueState) {
  if (typeof BroadcastChannel === "undefined") return;

  const channel = new BroadcastChannel(INPUT_QUEUE_CHANNEL_NAME);
  channel.postMessage({
    type: "input-queue-change",
    sessionId,
    state,
  });
  channel.close();
}

function mergeState(
  source: PersistedInputQueueState,
  target: PersistedInputQueueState,
): PersistedInputQueueState {
  const seen = new Set<string>();
  const items = [...target.items, ...source.items].filter((item) => {
    const id = item?.id;
    if (!id) return true;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });

  return normalizeState(
    {
      ...target,
      ...source,
      items,
      command: source.command ?? target.command,
      updatedAt: Date.now(),
    },
    Date.now(),
  );
}

export function migrateInputQueueStorage(fromSessionId: string, toSessionId: string) {
  if (!fromSessionId || !toSessionId || fromSessionId === toSessionId) {
    return false;
  }

  const source = readState(fromSessionId);
  if (isEmptyState(source)) return false;

  const target = readState(toSessionId);
  const next = isEmptyState(target) ? normalizeState(source) : mergeState(source, target);

  writeState(toSessionId, next);
  removeState(fromSessionId);
  broadcastState(toSessionId, next);
  broadcastState(fromSessionId, createEmptyState(next.updatedAt));

  return true;
}

export { getInputQueueStorageKey };
