import { create } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type QueueItemStatus = "pending" | "sending" | "failed" | "sent";

export type QueueRunState = "idle" | "running" | "paused" | "error";

/** Attachment reference (URL only, binary not stored in queue) */
export interface QueueAttachment {
  url: string;
  name?: string;
  type?: string;
  size?: number;
}

/** Image reference */
export interface QueueImage {
  url: string;
  thumbUrl?: string;
}

/** Mention reference */
export interface QueueMention {
  id: string;
  name: string;
}

/** Quote reference */
export interface QueueQuote {
  messageId: string;
  text: string;
}

/** Full message body for a queued item (Phase 3 ready) */
export interface QueueItem {
  id: string;
  text: string;
  attachments?: QueueAttachment[];
  images?: QueueImage[];
  mentions?: QueueMention[];
  quote?: QueueQuote;
  /** Agent ID captured at enqueue time to prevent cross-agent delivery */
  agentId?: string;
  /** Backend session_id captured at enqueue time so background sender uses
   *  the correct session even after agent switch clears the session list. */
  backendSessionId?: string;
  userId?: string;
  channel?: string;
  status: QueueItemStatus;
  retryCount: number;
  errorMessage?: string;
  createdAt: number;
}

/** Data required to enqueue a new item */
export interface QueueItemInput {
  text: string;
  attachments?: QueueAttachment[];
  images?: QueueImage[];
  mentions?: QueueMention[];
  quote?: QueueQuote;
  userId?: string;
  channel?: string;
}

// ---------------------------------------------------------------------------
// Storage helpers (localStorage; persists across browser close, sent items
// removed eagerly via remove())
// ---------------------------------------------------------------------------

export const STORAGE_PREFIX = "qwenpaw:message-queue:";

/** Shape persisted in localStorage per session */
interface PersistedQueue {
  items: QueueItem[];
  runState: QueueRunState;
}

export function getStorageKey(sessionId: string): string {
  return `${STORAGE_PREFIX}${sessionId}`;
}

function readQueueFromStorage(sessionId: string): PersistedQueue | null {
  try {
    const key = getStorageKey(sessionId);
    let saved = localStorage.getItem(key);
    // One-time migration from sessionStorage (older builds used sessionStorage)
    if (!saved) {
      try {
        const legacy = sessionStorage.getItem(key);
        if (legacy) {
          localStorage.setItem(key, legacy);
          sessionStorage.removeItem(key);
          saved = legacy;
        }
      } catch {
        // ignore
      }
    }
    if (saved) {
      const parsed = JSON.parse(saved);
      // Backward compat: old format was QueueItem[]
      if (Array.isArray(parsed)) {
        return { items: parsed as QueueItem[], runState: "idle" };
      }
      return parsed as PersistedQueue;
    }
  } catch {
    // ignore
  }
  return null;
}

function writeQueueToStorage(
  sessionId: string,
  items: QueueItem[],
  runState: QueueRunState,
) {
  try {
    if (items.length > 0) {
      localStorage.setItem(
        getStorageKey(sessionId),
        JSON.stringify({ items, runState }),
      );
    } else {
      localStorage.removeItem(getStorageKey(sessionId));
    }
  } catch {
    // ignore storage errors
  }
}

export function removeQueueFromStorage(sessionId: string) {
  try {
    localStorage.removeItem(getStorageKey(sessionId));
  } catch {
    // ignore
  }
  // Also clean any legacy sessionStorage entry
  try {
    sessionStorage.removeItem(getStorageKey(sessionId));
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// ID generator
// ---------------------------------------------------------------------------

let _nextQueueId = 0;
export function nextQueueId(): string {
  return "mq-" + Date.now().toString(36) + "-" + (++_nextQueueId).toString(36);
}

// ---------------------------------------------------------------------------
// Cross-tab synchronization
// ---------------------------------------------------------------------------

type BroadcastPayload = {
  type:
    | "enqueue"
    | "remove"
    | "edit"
    | "reorder"
    | "clear"
    | "setItemStatus"
    | "migrate"
    | "runState";
  sessionId: string;
  items?: QueueItem[];
  runState?: QueueRunState;
  // For migrate: target session id (sessionId is the source)
  toSessionId?: string;
};

let _channel: BroadcastChannel | null = null;
function getChannel(): BroadcastChannel | null {
  if (_channel) return _channel;
  if (typeof BroadcastChannel === "undefined") return null;
  try {
    _channel = new BroadcastChannel("qwenpaw:queue");
  } catch {
    _channel = null;
  }
  return _channel;
}

function broadcast(payload: BroadcastPayload) {
  const ch = getChannel();
  if (ch) {
    try {
      ch.postMessage(payload);
    } catch {
      // ignore
    }
  }
}

// ---------------------------------------------------------------------------
// Send lock (Web Locks API). Ensures only one tab actively sends per session.
// ---------------------------------------------------------------------------

type LockLike = { request: (...args: unknown[]) => Promise<unknown> };

function getLockManager(): LockLike | null {
  if (typeof navigator === "undefined") return null;
  const nav = navigator as Navigator & { locks?: LockLike };
  return nav.locks ?? null;
}

export async function withSendLock<T>(
  sessionId: string,
  fn: () => Promise<T> | T,
): Promise<T | null> {
  const locks = getLockManager();
  if (!locks) {
    // Environment doesn't support Web Locks: degrade to direct execution
    return await fn();
  }
  try {
    const result = (await locks.request(
      `qwenpaw:queue-send:${sessionId}`,
      { ifAvailable: true },
      async (lock: unknown) => {
        if (!lock) return null;
        return await fn();
      },
    )) as T | null;
    return result;
  } catch {
    return null;
  }
}

/**
 * Hold a persistent exclusive ownership lock for a conversation. Only one
 * tab in the entire browser holds this lock at any time per session id.
 *
 * - Resolves `onAcquired()` when the lock is granted (this tab becomes the
 *   owner / active sender).
 * - Holds the lock until `abortSignal` is aborted (e.g. on component unmount
 *   or when the queueSessionId changes).
 * - Other tabs requesting the same lock will wait; when the current owner
 *   releases (page closed, navigated away, signal aborted), one of the
 *   waiters automatically becomes the new owner.
 * - Falls back to immediate ownership when Web Locks are unavailable, so
 *   single-tab functionality is preserved.
 */
export function holdOwnershipLock(
  sessionId: string,
  onAcquired: () => void,
  abortSignal: AbortSignal,
): Promise<void> {
  const locks = getLockManager();
  if (!locks) {
    onAcquired();
    return Promise.resolve();
  }
  return locks
    .request(
      `qwenpaw:queue-owner:${sessionId}`,
      { mode: "exclusive", signal: abortSignal },
      async (lock: unknown) => {
        if (!lock) return;
        if (abortSignal.aborted) return;
        onAcquired();
        // Hold the lock until the caller aborts.
        await new Promise<void>((resolve) => {
          if (abortSignal.aborted) {
            resolve();
            return;
          }
          abortSignal.addEventListener("abort", () => resolve(), {
            once: true,
          });
        });
      },
    )
    .then(() => undefined)
    .catch(() => undefined);
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface MessageQueueStore {
  /** All session queues: sessionId -> items */
  queues: Record<string, QueueItem[]>;
  /** Per-session run state: sessionId -> QueueRunState (replaces global runState) */
  runStates: Record<string, QueueRunState>;
  /** Currently sending item ID */
  currentSendingId: string | null;
  /**
   * Marks the most recent migrate target. The Chat page uses this to skip
   * loadFromStorage right after a migration (the in-memory state is already
   * authoritative).
   */
  lastMigratedTo: string | null;

  // Actions
  enqueue: (sessionId: string, input: QueueItemInput) => void;
  remove: (sessionId: string, id: string) => void;
  edit: (sessionId: string, id: string, text: string) => void;
  reorder: (sessionId: string, items: QueueItem[]) => void;
  clear: (sessionId: string) => void;
  /** Move all items from one session id to another (and clear the source). */
  migrateQueue: (fromSessionId: string, toSessionId: string) => void;
  setItemStatus: (
    sessionId: string,
    id: string,
    status: QueueItemStatus,
    errorMessage?: string,
  ) => void;
  /** Set run state for a specific session (persists to localStorage). */
  setRunState: (sessionId: string, state: QueueRunState) => void;
  /** Get run state for a specific session (defaults to "idle"). */
  getRunState: (sessionId: string) => QueueRunState;
  setCurrentSendingId: (id: string | null) => void;
  consumeMigratedTo: () => string | null;
  /** Get queue for a session (read-only) */
  getQueue: (sessionId: string) => QueueItem[];
  /** Persist queue to localStorage */
  persistToStorage: (sessionId: string) => void;
  /** Load queue from localStorage into memory */
  loadFromStorage: (sessionId: string) => void;
  /** Internal: apply a remote (cross-tab) update without re-broadcasting. */
  applyRemoteItems: (sessionId: string, items: QueueItem[]) => void;
  /** Internal: apply a remote run-state update without re-broadcasting. */
  applyRemoteRunState: (sessionId: string, runState: QueueRunState) => void;
}

/** Maximum number of items allowed in a single session queue */
export const MAX_QUEUE_SIZE = 50;

export const useMessageQueueStore = create<MessageQueueStore>((set, get) => ({
  queues: {},
  runStates: {},
  currentSendingId: null,
  lastMigratedTo: null,

  enqueue: (sessionId: string, input: QueueItemInput) => {
    const current = get().queues[sessionId] ?? [];
    if (current.length >= MAX_QUEUE_SIZE) {
      // Queue is full, reject
      return;
    }
    // Capture the current selected agent at enqueue time so that
    // background sending uses the correct X-Agent-Id even after switch.
    let agentId: string | undefined;
    try {
      const agentStorage =
        sessionStorage.getItem("qwenpaw-agent-storage") ||
        localStorage.getItem("qwenpaw-agent-storage");
      if (agentStorage) {
        const parsed = JSON.parse(agentStorage);
        agentId = parsed?.state?.selectedAgent || undefined;
      }
    } catch {
      // ignore
    }
    // Capture backend session_id so background sender targets the correct
    // session even if the session list is cleared after agent switch.
    const backendSessionId =
      (window as unknown as { currentSessionId?: string }).currentSessionId ||
      undefined;
    const item: QueueItem = {
      id: nextQueueId(),
      text: input.text,
      attachments: input.attachments,
      images: input.images,
      mentions: input.mentions,
      quote: input.quote,
      agentId,
      backendSessionId,
      userId: input.userId,
      channel: input.channel,
      status: "pending",
      retryCount: 0,
      createdAt: Date.now(),
    };
    set((state) => {
      const nextItems = [...current, item];
      const next = { ...state.queues, [sessionId]: nextItems };
      writeQueueToStorage(
        sessionId,
        nextItems,
        get().runStates[sessionId] ?? "idle",
      );
      broadcast({ type: "enqueue", sessionId, items: nextItems });
      return { queues: next };
    });
  },

  remove: (sessionId: string, id: string) => {
    set((state) => {
      const current = state.queues[sessionId] ?? [];
      const nextItems = current.filter((it) => it.id !== id);
      const next = { ...state.queues, [sessionId]: nextItems };
      writeQueueToStorage(
        sessionId,
        nextItems,
        get().runStates[sessionId] ?? "idle",
      );
      broadcast({ type: "remove", sessionId, items: nextItems });
      return { queues: next };
    });
  },

  edit: (sessionId: string, id: string, text: string) => {
    set((state) => {
      const current = state.queues[sessionId] ?? [];
      const nextItems = current.map((it) =>
        it.id === id ? { ...it, text } : it,
      );
      const next = { ...state.queues, [sessionId]: nextItems };
      writeQueueToStorage(
        sessionId,
        nextItems,
        get().runStates[sessionId] ?? "idle",
      );
      broadcast({ type: "edit", sessionId, items: nextItems });
      return { queues: next };
    });
  },

  reorder: (sessionId: string, items: QueueItem[]) => {
    set((state) => {
      const next = { ...state.queues, [sessionId]: items };
      writeQueueToStorage(
        sessionId,
        items,
        get().runStates[sessionId] ?? "idle",
      );
      broadcast({ type: "reorder", sessionId, items });
      return { queues: next };
    });
  },

  clear: (sessionId: string) => {
    set((state) => {
      const queues = { ...state.queues };
      delete queues[sessionId];
      const runStates = { ...state.runStates };
      delete runStates[sessionId];
      writeQueueToStorage(sessionId, [], "idle");
      broadcast({ type: "clear", sessionId, items: [] });
      return { queues, runStates };
    });
  },

  migrateQueue: (fromSessionId: string, toSessionId: string) => {
    if (fromSessionId === toSessionId) return;
    set((state) => {
      const fromItems = state.queues[fromSessionId] ?? [];
      const toItems = state.queues[toSessionId] ?? [];
      // Preserve order: existing destination items first, migrated source items appended.
      const merged = [...toItems, ...fromItems];
      const queues = { ...state.queues, [toSessionId]: merged };
      delete queues[fromSessionId];
      // Carry over the from-session's runState to the destination if not already set.
      const runStates = { ...state.runStates };
      if (!runStates[toSessionId] && runStates[fromSessionId]) {
        runStates[toSessionId] = runStates[fromSessionId];
      }
      delete runStates[fromSessionId];
      const destRunState = runStates[toSessionId] ?? "idle";
      writeQueueToStorage(toSessionId, merged, destRunState);
      writeQueueToStorage(fromSessionId, [], "idle");
      broadcast({
        type: "migrate",
        sessionId: fromSessionId,
        toSessionId,
        items: merged,
      });
      return { queues, runStates, lastMigratedTo: toSessionId };
    });
  },

  setItemStatus: (
    sessionId: string,
    id: string,
    status: QueueItemStatus,
    errorMessage?: string,
  ) => {
    set((state) => {
      const current = state.queues[sessionId] ?? [];
      const nextItems = current.map((it) =>
        it.id === id
          ? {
              ...it,
              status,
              errorMessage,
              retryCount: it.retryCount + (status === "failed" ? 1 : 0),
            }
          : it,
      );
      const next = { ...state.queues, [sessionId]: nextItems };
      writeQueueToStorage(
        sessionId,
        nextItems,
        get().runStates[sessionId] ?? "idle",
      );
      broadcast({ type: "setItemStatus", sessionId, items: nextItems });
      return { queues: next };
    });
  },

  setRunState: (sessionId: string, runState: QueueRunState) => {
    set((state) => ({
      runStates: { ...state.runStates, [sessionId]: runState },
    }));
    // Always persist with the correct session key.
    const items = get().queues[sessionId] ?? [];
    writeQueueToStorage(sessionId, items, runState);
    broadcast({
      type: "runState",
      sessionId,
      runState,
    });
  },

  getRunState: (sessionId: string): QueueRunState => {
    return get().runStates[sessionId] ?? "idle";
  },

  setCurrentSendingId: (currentSendingId: string | null) => {
    set({ currentSendingId });
  },

  consumeMigratedTo: () => {
    const v = get().lastMigratedTo;
    if (v !== null) set({ lastMigratedTo: null });
    return v;
  },

  getQueue: (sessionId: string) => {
    return get().queues[sessionId] ?? [];
  },

  persistToStorage: (sessionId: string) => {
    const items = get().queues[sessionId] ?? [];
    writeQueueToStorage(sessionId, items, get().runStates[sessionId] ?? "idle");
  },

  loadFromStorage: (sessionId: string) => {
    const saved = readQueueFromStorage(sessionId);
    if (saved) {
      set((state) => ({
        queues: { ...state.queues, [sessionId]: saved.items },
        // Restore persisted runState per-session (avoids auto-send after refresh
        // when the queue was paused). Default to "idle" if not paused.
        runStates: {
          ...state.runStates,
          [sessionId]: saved.runState === "paused" ? "paused" : "idle",
        },
      }));
    } else {
      // Ensure stale in-memory state is cleared so callers see an empty queue.
      set((state) => {
        if (!(sessionId in state.queues)) return state;
        const queues = { ...state.queues };
        delete queues[sessionId];
        return { queues };
      });
    }
  },

  applyRemoteItems: (sessionId: string, items: QueueItem[]) => {
    set((state) => {
      const queues = { ...state.queues };
      if (items.length === 0) {
        delete queues[sessionId];
      } else {
        queues[sessionId] = items;
      }
      return { queues };
    });
  },

  applyRemoteRunState: (sessionId: string, runState: QueueRunState) => {
    set((state) => ({
      runStates: { ...state.runStates, [sessionId]: runState },
    }));
  },
}));

// ---------------------------------------------------------------------------
// Cross-tab listeners. These mutate in-memory state only; they never re-write
// storage or re-broadcast (which would loop).
// ---------------------------------------------------------------------------

if (typeof window !== "undefined") {
  // BroadcastChannel: same-origin, instant updates between tabs.
  const ch = getChannel();
  if (ch) {
    ch.addEventListener("message", (event: MessageEvent<BroadcastPayload>) => {
      const data = event.data;
      if (!data || typeof data !== "object") return;
      const store = useMessageQueueStore.getState();
      if (data.type === "migrate") {
        // Source cleared, destination set with merged items.
        store.applyRemoteItems(data.sessionId, []);
        if (data.toSessionId && data.items) {
          store.applyRemoteItems(data.toSessionId, data.items);
        }
        return;
      }
      if (data.type === "runState" && data.runState) {
        useMessageQueueStore
          .getState()
          .applyRemoteRunState(data.sessionId, data.runState);
        return;
      }
      if (data.items) {
        store.applyRemoteItems(data.sessionId, data.items);
      }
    });
  }

  // storage event: fallback for environments without BroadcastChannel, and
  // also covers the case where another tab wrote without our channel.
  window.addEventListener("storage", (event) => {
    if (!event.key || !event.key.startsWith(STORAGE_PREFIX)) return;
    const sessionId = event.key.slice(STORAGE_PREFIX.length);
    const store = useMessageQueueStore.getState();
    if (event.newValue == null) {
      store.applyRemoteItems(sessionId, []);
      return;
    }
    try {
      const parsed = JSON.parse(event.newValue);
      const items: QueueItem[] = Array.isArray(parsed)
        ? (parsed as QueueItem[])
        : (parsed as PersistedQueue).items ?? [];
      store.applyRemoteItems(sessionId, items);
      if (
        !Array.isArray(parsed) &&
        (parsed as PersistedQueue).runState === "paused"
      ) {
        useMessageQueueStore
          .getState()
          .applyRemoteRunState(sessionId, "paused");
      }
    } catch {
      // ignore
    }
  });
}
