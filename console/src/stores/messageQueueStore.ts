import { create } from "zustand";
import {
  createClientMessageId,
  extractClientMessageId,
} from "../utils/clientMessageId";

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
  clientMessageId?: string;
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
  requestContext?: Record<string, unknown>;
  bizParams?: Record<string, unknown>;
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
  /** Explicit route snapshot. Callers should provide these when available. */
  agentId?: string;
  backendSessionId?: string;
  userId?: string;
  channel?: string;
  requestContext?: Record<string, unknown>;
  bizParams?: Record<string, unknown>;
}

/** Chat UUIDs are globally unique. Drafts have no UUID and must be Agent-scoped.
 * These keys belong only to storage/locks; never send them to the Chat API. */
export function getQueueKey(agentId: string, chatId?: string | null): string {
  return !chatId || chatId === "new"
    ? `draft:${encodeURIComponent(agentId || "default")}`
    : chatId;
}

export function isDraftQueueKey(key: string): boolean {
  return key === "new" || key.startsWith("draft:");
}

/** Locate an item after a `new` queue has migrated to its backend chat id. */
export function findQueueItemSessionId(
  queues: Record<string, QueueItem[]>,
  itemId: string,
  preferredSessionId?: string,
): string | undefined {
  if (
    preferredSessionId &&
    queues[preferredSessionId]?.some((item) => item.id === itemId)
  ) {
    return preferredSessionId;
  }
  return Object.entries(queues).find(([, items]) =>
    items.some((item) => item.id === itemId),
  )?.[0];
}

/**
 * Return the session that most recently received a queued item for an agent.
 *
 * Queue state is synchronized across tabs, so it is the authoritative host
 * signal when another tab is actively working in an agent session. Legacy
 * queue items without an agentId belong to the default agent.
 */
export function getLatestQueuedSessionIdForAgent(
  queues: Record<string, QueueItem[]>,
  agentId: string,
): string | undefined {
  let latestSessionId: string | undefined;
  let latestCreatedAt = Number.NEGATIVE_INFINITY;

  for (const [sessionId, items] of Object.entries(queues)) {
    if (isDraftQueueKey(sessionId)) continue;
    for (const item of items) {
      if ((item.agentId ?? "default") !== agentId) continue;
      if (item.createdAt <= latestCreatedAt) continue;
      latestCreatedAt = item.createdAt;
      latestSessionId = sessionId;
    }
  }

  return latestSessionId;
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
  sourceItems?: QueueItem[];
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
 * Run a background queue sender only when no mounted foreground tab owns the
 * conversation. Unlike `holdOwnershipLock`, this never waits: a missing lock
 * means the foreground owner is responsible for consuming the queue and
 * rendering its stream.
 */
export async function withAvailableOwnershipLock<T>(
  sessionId: string,
  fn: () => Promise<T> | T,
): Promise<T | null> {
  const locks = getLockManager();
  if (!locks) {
    return await fn();
  }
  try {
    const result = (await locks.request(
      `qwenpaw:queue-owner:${sessionId}`,
      { mode: "exclusive", ifAvailable: true },
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

/** Acquire both the foreground ownership gate and the short-lived send lock. */
export function withBackgroundSendLock<T>(
  sessionId: string,
  fn: () => Promise<T> | T,
): Promise<T | null> {
  return withAvailableOwnershipLock(sessionId, () =>
    withSendLock(sessionId, fn),
  );
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
  migrateQueue: (
    fromSessionId: string,
    toSessionId: string,
    agentId?: string,
  ) => void;
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
  /** Remove only messages whose unique receipt is present in backend history. */
  reconcileHistory: (
    sessionId: string,
    agentId: string,
    messages: Array<{ role?: string; metadata?: unknown }>,
  ) => void;
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
    let agentId = input.agentId;
    try {
      if (!agentId) {
        const agentStorage =
          sessionStorage.getItem("qwenpaw-agent-storage") ||
          localStorage.getItem("qwenpaw-agent-storage");
        if (agentStorage) {
          const parsed = JSON.parse(agentStorage);
          agentId = parsed?.state?.selectedAgent || undefined;
        }
      }
    } catch {
      // ignore
    }
    // Capture backend session_id so background sender targets the correct
    // session even if the session list is cleared after agent switch.
    const backendSessionId = input.backendSessionId;
    const item: QueueItem = {
      id: nextQueueId(),
      clientMessageId: createClientMessageId(),
      text: input.text,
      attachments: input.attachments,
      images: input.images,
      mentions: input.mentions,
      quote: input.quote,
      agentId,
      backendSessionId,
      userId: input.userId,
      channel: input.channel,
      requestContext: input.requestContext,
      bizParams: input.bizParams,
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

  migrateQueue: (
    fromSessionId: string,
    toSessionId: string,
    agentId?: string,
  ) => {
    if (fromSessionId === toSessionId) return;
    set((state) => {
      const fromItems = state.queues[fromSessionId] ?? [];
      const moving = agentId
        ? fromItems.filter((item) => (item.agentId || "default") === agentId)
        : fromItems;
      if (moving.length === 0 && (agentId || !state.runStates[fromSessionId]))
        return state;
      const movingIds = new Set(moving.map((item) => item.id));
      const remaining = fromItems.filter((item) => !movingIds.has(item.id));
      const toItems = state.queues[toSessionId] ?? [];
      // Preserve order: existing destination items first, migrated source items appended.
      const existingIds = new Set(toItems.map((item) => item.id));
      const merged = [
        ...toItems,
        ...moving.filter((item) => !existingIds.has(item.id)),
      ];
      const queues = { ...state.queues, [toSessionId]: merged };
      if (remaining.length) queues[fromSessionId] = remaining;
      else delete queues[fromSessionId];
      // Carry over the from-session's runState to the destination if not already set.
      const runStates = { ...state.runStates };
      if (!runStates[toSessionId] && runStates[fromSessionId]) {
        runStates[toSessionId] = runStates[fromSessionId];
      }
      if (!remaining.length) delete runStates[fromSessionId];
      const destRunState = runStates[toSessionId] ?? "idle";
      writeQueueToStorage(toSessionId, merged, destRunState);
      writeQueueToStorage(
        fromSessionId,
        remaining,
        runStates[fromSessionId] ?? "idle",
      );
      broadcast({
        type: "migrate",
        sessionId: fromSessionId,
        toSessionId,
        items: merged,
        sourceItems: remaining,
        runState: destRunState,
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
      const failed = status === "failed" && current.some((it) => it.id === id);
      const runState = failed ? "error" : state.runStates[sessionId] ?? "idle";
      const runStates = { ...state.runStates, [sessionId]: runState };
      writeQueueToStorage(sessionId, nextItems, runState);
      broadcast({
        type: "setItemStatus",
        sessionId,
        items: nextItems,
        runState,
      });
      return { queues: next, runStates };
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

  reconcileHistory: (sessionId, agentId, messages) => {
    const received = new Set(
      messages
        .filter((message) => message.role === "user")
        .map((message) => extractClientMessageId(message.metadata))
        .filter(Boolean),
    );
    if (received.size === 0) return;
    const saved = readQueueFromStorage(sessionId);
    const current = get().queues[sessionId] ?? saved?.items ?? [];
    const items = current.filter(
      (item) =>
        (item.agentId || "default") !== agentId ||
        !item.clientMessageId ||
        !received.has(item.clientMessageId),
    );
    if (items.length === current.length) return;
    const previous = get().runStates[sessionId] ?? saved?.runState ?? "idle";
    const runState =
      previous === "error" && !items.some((item) => item.status === "failed")
        ? "idle"
        : previous;
    writeQueueToStorage(sessionId, items, runState);
    set((state) => ({
      queues: { ...state.queues, [sessionId]: items },
      runStates: { ...state.runStates, [sessionId]: runState },
    }));
    broadcast({ type: "setItemStatus", sessionId, items, runState });
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
        // A failed head requires an explicit retry, including for older saves
        // that recorded its item status without recording the error run state.
        runStates: {
          ...state.runStates,
          [sessionId]:
            saved.runState === "paused"
              ? "paused"
              : saved.runState === "error" ||
                saved.items[0]?.status === "failed"
              ? "error"
              : "idle",
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

/** Recover legacy drafts before acquiring foreground ownership. A separate
 * exclusive lock serializes the shared legacy read/partition/write across tabs. */
export async function recoverLegacyDraftQueue(
  queueKey: string,
  signal?: AbortSignal,
): Promise<void> {
  if (
    !queueKey.startsWith("draft:") ||
    !readQueueFromStorage("new")?.items.length
  )
    return;
  const recover = () => {
    if (signal?.aborted) return;
    const legacy = readQueueFromStorage("new");
    if (!legacy?.items.length) return;
    const store = useMessageQueueStore.getState();
    store.loadFromStorage("new");
    store.loadFromStorage(queueKey);
    store.migrateQueue("new", queueKey, decodeURIComponent(queueKey.slice(6)));
  };
  const locks = getLockManager();
  if (!locks) {
    recover();
    return;
  }
  try {
    await locks.request(
      "qwenpaw:queue-migrate:legacy-new",
      { mode: "exclusive", signal },
      recover,
    );
  } catch (error) {
    if (!signal?.aborted) throw error;
  }
}

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
        store.applyRemoteItems(data.sessionId, data.sourceItems ?? []);
        if (data.toSessionId && data.items) {
          if (data.runState) {
            store.applyRemoteRunState(data.toSessionId, data.runState);
          }
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
      if (data.runState) {
        store.applyRemoteRunState(data.sessionId, data.runState);
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
        ["paused", "error"].includes((parsed as PersistedQueue).runState)
      ) {
        useMessageQueueStore
          .getState()
          .applyRemoteRunState(sessionId, (parsed as PersistedQueue).runState);
      }
    } catch {
      // ignore
    }
  });
}
