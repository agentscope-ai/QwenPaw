const INPUT_QUEUE_STORAGE_PREFIX = "agentscope-runtime-webui-input-queue";
const INPUT_QUEUE_MUTATION_LOCK_PREFIX =
  "agentscope-runtime-webui-input-queue-mutate";
const LEGACY_MESSAGE_QUEUE_STORAGE_PREFIX = "qwenpaw:message-queue:";

interface InputQueueStateSnapshot {
  items?: unknown[];
  paused?: boolean;
  ownerTabId?: string;
  ownerUpdatedAt?: number;
  command?: unknown;
  updatedAt?: number;
}

function getInputQueueStorageKey(sessionId: string) {
  return `${INPUT_QUEUE_STORAGE_PREFIX}:${sessionId}`;
}

function parseQueueState(value: string | null): InputQueueStateSnapshot {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object"
      ? (parsed as InputQueueStateSnapshot)
      : {};
  } catch {
    return {};
  }
}

function getQueueItemIdentity(item: unknown) {
  if (!item || typeof item !== "object") return undefined;
  const maybeId = (item as { id?: unknown }).id;
  return typeof maybeId === "string" && maybeId ? maybeId : undefined;
}

function mergeQueueItems(
  fromItems: unknown[] | undefined,
  toItems: unknown[] | undefined,
) {
  const merged: unknown[] = [];
  const itemIndexById = new Map<string, number>();

  for (const item of Array.isArray(fromItems) ? fromItems : []) {
    const itemId = getQueueItemIdentity(item);
    if (itemId) {
      itemIndexById.set(itemId, merged.length);
    }
    merged.push(item);
  }

  for (const item of Array.isArray(toItems) ? toItems : []) {
    const itemId = getQueueItemIdentity(item);
    const existingIndex = itemId ? itemIndexById.get(itemId) : undefined;
    if (existingIndex !== undefined) {
      // The destination can already contain an edited/retried copy of the same
      // SDK item. Keep its newer data while preserving the item's FIFO slot.
      merged[existingIndex] = item;
      continue;
    }
    if (itemId) {
      itemIndexById.set(itemId, merged.length);
    }
    merged.push(item);
  }

  return merged;
}

function hasQueueWork(state: InputQueueStateSnapshot) {
  return (
    (Array.isArray(state.items) && state.items.length > 0) || !!state.command
  );
}

function shouldRemoveQueueState(state: InputQueueStateSnapshot) {
  return !hasQueueWork(state) && !state.ownerTabId && !state.paused;
}

export function hasStoredInputQueueItems(sessionId: string | undefined) {
  if (!sessionId) return false;
  try {
    const state = parseQueueState(
      localStorage.getItem(getInputQueueStorageKey(sessionId)),
    );
    return Array.isArray(state.items) && state.items.length > 0;
  } catch {
    return false;
  }
}

export function clearStoredInputQueue(sessionId: string | undefined) {
  if (!sessionId) return;
  try {
    const key = getInputQueueStorageKey(sessionId);
    const oldValue = localStorage.getItem(key);
    if (oldValue === null) return;
    localStorage.removeItem(key);
    notifyQueueStorageChange(key, oldValue, null);
  } catch {
    // Local storage can be unavailable in some browser modes.
  }
}

export function clearLegacyStoredMessageQueue(sessionId: string | undefined) {
  if (!sessionId) return;
  const key = `${LEGACY_MESSAGE_QUEUE_STORAGE_PREFIX}${sessionId}`;
  try {
    localStorage.removeItem(key);
  } catch {
    // Local storage can be unavailable in some browser modes.
  }
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Session storage can be unavailable in some browser modes.
  }
}

function notifyQueueStorageChange(
  key: string,
  oldValue: string | null,
  newValue: string | null,
) {
  if (typeof window === "undefined") return;
  try {
    window.dispatchEvent(
      new StorageEvent("storage", {
        key,
        oldValue,
        newValue,
        storageArea: localStorage,
      }),
    );
  } catch {
    // Same-tab notification is best-effort; peer tabs still receive storage events.
  }
}

type QueueLocks = {
  request: <T>(
    name: string,
    options: { mode: "exclusive" },
    callback: () => T | Promise<T>,
  ) => Promise<T>;
};

function getQueueLocks() {
  return typeof navigator === "undefined"
    ? undefined
    : (navigator as typeof navigator & { locks?: QueueLocks }).locks;
}

async function withQueueMutationLocks<T>(
  queueSessionIds: string[],
  callback: () => T | Promise<T>,
): Promise<T> {
  const locks = getQueueLocks();
  if (!locks?.request) return callback();

  const lockNames = Array.from(new Set(queueSessionIds))
    .map((sessionId) => `${INPUT_QUEUE_MUTATION_LOCK_PREFIX}:${sessionId}`)
    .sort();

  const acquire = (index: number): Promise<T> => {
    if (index >= lockNames.length) return Promise.resolve(callback());
    return locks.request(lockNames[index], { mode: "exclusive" }, () =>
      acquire(index + 1),
    );
  };

  return acquire(0);
}

export async function migrateInputQueueStorage(
  fromQueueSessionId: string | undefined,
  toQueueSessionId: string | undefined,
) {
  if (!fromQueueSessionId || !toQueueSessionId) return;
  if (fromQueueSessionId === toQueueSessionId) return;

  try {
    await withQueueMutationLocks([fromQueueSessionId, toQueueSessionId], () => {
      const fromKey = getInputQueueStorageKey(fromQueueSessionId);
      const toKey = getInputQueueStorageKey(toQueueSessionId);
      const fromRawState = localStorage.getItem(fromKey);
      if (!fromRawState) return;

      const toRawState = localStorage.getItem(toKey);
      const fromState = parseQueueState(fromRawState);
      const toState = parseQueueState(toRawState);
      const mergedState: InputQueueStateSnapshot = {
        ...fromState,
        ...toState,
        items: mergeQueueItems(fromState.items, toState.items),
        paused: !!fromState.paused || !!toState.paused,
        ownerTabId: toState.ownerTabId || fromState.ownerTabId,
        ownerUpdatedAt: toState.ownerUpdatedAt ?? fromState.ownerUpdatedAt,
        command: toState.command ?? fromState.command,
        updatedAt: Date.now(),
      };
      const nextRawState = shouldRemoveQueueState(mergedState)
        ? null
        : JSON.stringify(mergedState);

      localStorage.removeItem(fromKey);
      if (nextRawState) {
        localStorage.setItem(toKey, nextRawState);
      } else {
        localStorage.removeItem(toKey);
      }

      notifyQueueStorageChange(fromKey, fromRawState, null);
      notifyQueueStorageChange(toKey, toRawState, nextRawState);
    });
  } catch {
    // Local storage can be unavailable in some browser modes.
  }
}
