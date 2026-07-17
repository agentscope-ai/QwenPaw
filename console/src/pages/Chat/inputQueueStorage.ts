const INPUT_QUEUE_STORAGE_PREFIX = "agentscope-runtime-webui-input-queue";

interface InputQueueStateSnapshot {
  items?: unknown[];
  paused?: boolean;
  ownerTabId?: string;
  ownerUpdatedAt?: number;
  command?: unknown;
  updatedAt?: number;
}

interface StoredInputQueueItem {
  id?: string;
  data?: {
    qwenpaw_queue_request_id?: unknown;
    biz_params?: { __qwenpaw_queue_request_id?: unknown };
  };
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
  const seen = new Set<string>();

  for (const item of [
    ...(Array.isArray(fromItems) ? fromItems : []),
    ...(Array.isArray(toItems) ? toItems : []),
  ]) {
    const itemId = getQueueItemIdentity(item);
    if (itemId) {
      if (seen.has(itemId)) continue;
      seen.add(itemId);
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

export function removeStoredInputQueueItem(
  sessionId: string,
  acceptedRequestId: string,
) {
  try {
    const key = getInputQueueStorageKey(sessionId);
    const oldValue = localStorage.getItem(key);
    const state = parseQueueState(oldValue);
    const items = Array.isArray(state.items) ? state.items : [];
    const acceptedIndex = items.findIndex((item) => {
      const data = (item as StoredInputQueueItem)?.data;
      return (
        data?.qwenpaw_queue_request_id === acceptedRequestId ||
        data?.biz_params?.__qwenpaw_queue_request_id === acceptedRequestId
      );
    });
    if (acceptedIndex < 0) return false;

    const nextState: InputQueueStateSnapshot = {
      ...state,
      items: items.filter((_, index) => index !== acceptedIndex),
      updatedAt: Date.now(),
    };
    const nextValue = shouldRemoveQueueState(nextState)
      ? null
      : JSON.stringify(nextState);
    if (nextValue) {
      localStorage.setItem(key, nextValue);
    } else {
      localStorage.removeItem(key);
    }
    notifyQueueStorageChange(key, oldValue, nextValue);
    return true;
  } catch {
    return false;
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

export function migrateInputQueueStorage(
  fromQueueSessionId: string | undefined,
  toQueueSessionId: string | undefined,
) {
  if (!fromQueueSessionId || !toQueueSessionId) return;
  if (fromQueueSessionId === toQueueSessionId) return;

  const fromKey = getInputQueueStorageKey(fromQueueSessionId);
  const toKey = getInputQueueStorageKey(toQueueSessionId);
  try {
    const fromRawState = localStorage.getItem(fromKey);
    if (!fromRawState) return;

    const toRawState = localStorage.getItem(toKey);
    const fromState = parseQueueState(fromRawState);
    const toState = parseQueueState(toRawState);
    const now = Date.now();
    const mergedState: InputQueueStateSnapshot = {
      ...fromState,
      ...toState,
      items: mergeQueueItems(fromState.items, toState.items),
      paused: !!fromState.paused || !!toState.paused,
      ownerTabId: toState.ownerTabId || fromState.ownerTabId,
      ownerUpdatedAt: toState.ownerUpdatedAt ?? fromState.ownerUpdatedAt,
      command: toState.command ?? fromState.command,
      updatedAt: now,
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
  } catch {
    // Local storage can be unavailable in some browser modes.
  }
}
