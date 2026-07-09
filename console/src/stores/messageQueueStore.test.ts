import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  useMessageQueueStore,
  STORAGE_PREFIX,
  getStorageKey,
  removeQueueFromStorage,
  nextQueueId,
  MAX_QUEUE_SIZE,
  withSendLock,
  holdOwnershipLock,
} from "./messageQueueStore";

const SESSION_ID = "sess-1";

function resetStore() {
  useMessageQueueStore.setState({
    queues: {},
    runStates: {},
    currentSendingId: null,
    lastMigratedTo: null,
  });
}

function clearStorage() {
  try {
    localStorage.clear();
  } catch {
    // ignore
  }
  try {
    sessionStorage.clear();
  } catch {
    // ignore
  }
}

describe("messageQueueStore", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
    vi.clearAllMocks();
  });

  afterEach(() => {
    resetStore();
    clearStorage();
  });

  // ---------------------------------------------------------------------------
  // Constants / helpers
  // ---------------------------------------------------------------------------

  it("STORAGE_PREFIX is 'qwenpaw:message-queue:'", () => {
    expect(STORAGE_PREFIX).toBe("qwenpaw:message-queue:");
  });

  it("getStorageKey concatenates prefix + sessionId", () => {
    expect(getStorageKey("abc")).toBe("qwenpaw:message-queue:abc");
  });

  it("MAX_QUEUE_SIZE is 50", () => {
    expect(MAX_QUEUE_SIZE).toBe(50);
  });

  it("nextQueueId returns unique monotonically increasing ids", () => {
    const a = nextQueueId();
    const b = nextQueueId();
    const c = nextQueueId();
    expect(a).not.toBe(b);
    expect(b).not.toBe(c);
    expect(a.startsWith("mq-")).toBe(true);
  });

  it("removeQueueFromStorage removes the entry from localStorage", () => {
    localStorage.setItem(getStorageKey(SESSION_ID), "sentinel");
    removeQueueFromStorage(SESSION_ID);
    expect(localStorage.getItem(getStorageKey(SESSION_ID))).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // Initial state
  // ---------------------------------------------------------------------------

  it("starts with empty queues, runStates, null currentSendingId and lastMigratedTo", () => {
    const state = useMessageQueueStore.getState();
    expect(state.queues).toEqual({});
    expect(state.runStates).toEqual({});
    expect(state.currentSendingId).toBeNull();
    expect(state.lastMigratedTo).toBeNull();
  });

  it("getQueue returns [] for an unknown session", () => {
    expect(useMessageQueueStore.getState().getQueue("unknown")).toEqual([]);
  });

  it("getRunState defaults to 'idle' for an unknown session", () => {
    expect(useMessageQueueStore.getState().getRunState("unknown")).toBe("idle");
  });

  // ---------------------------------------------------------------------------
  // enqueue
  // ---------------------------------------------------------------------------

  it("enqueue creates a pending item with the given text", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "hello" });

    const queue = useMessageQueueStore.getState().getQueue(SESSION_ID);
    expect(queue).toHaveLength(1);
    expect(queue[0].text).toBe("hello");
    expect(queue[0].status).toBe("pending");
    expect(queue[0].retryCount).toBe(0);
    expect(queue[0].createdAt).toBeGreaterThan(0);
  });

  it("enqueue appends multiple items preserving order", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "one" });
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "two" });
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "three" });

    const queue = useMessageQueueStore.getState().getQueue(SESSION_ID);
    expect(queue.map((i) => i.text)).toEqual(["one", "two", "three"]);
  });

  it("enqueue persists items to localStorage under the session key", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "persisted" });

    const raw = localStorage.getItem(getStorageKey(SESSION_ID));
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw as string);
    expect(parsed.items).toHaveLength(1);
    expect(parsed.items[0].text).toBe("persisted");
    expect(parsed.runState).toBe("idle");
  });

  it("enqueue rejects when the queue is already at MAX_QUEUE_SIZE", () => {
    for (let i = 0; i < MAX_QUEUE_SIZE; i++) {
      useMessageQueueStore
        .getState()
        .enqueue(SESSION_ID, { text: `item-${i}` });
    }
    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)).toHaveLength(
      MAX_QUEUE_SIZE,
    );

    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "overflow" });

    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)).toHaveLength(
      MAX_QUEUE_SIZE,
    );
    expect(
      useMessageQueueStore
        .getState()
        .getQueue(SESSION_ID)
        .some((i) => i.text === "overflow"),
    ).toBe(false);
  });

  it("enqueue captures agentId from sessionStorage when available", () => {
    sessionStorage.setItem(
      "qwenpaw-agent-storage",
      JSON.stringify({ state: { selectedAgent: "agent-x" } }),
    );

    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "hi" });

    const item = useMessageQueueStore.getState().getQueue(SESSION_ID)[0];
    expect(item.agentId).toBe("agent-x");
  });

  it("enqueue captures backendSessionId from window.currentSessionId when set", () => {
    (window as unknown as { currentSessionId?: string }).currentSessionId =
      "backend-42";

    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "hi" });

    const item = useMessageQueueStore.getState().getQueue(SESSION_ID)[0];
    expect(item.backendSessionId).toBe("backend-42");

    delete (window as unknown as { currentSessionId?: string })
      .currentSessionId;
  });

  it("enqueue leaves agentId/backendSessionId undefined when none are set", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "hi" });

    const item = useMessageQueueStore.getState().getQueue(SESSION_ID)[0];
    expect(item.agentId).toBeUndefined();
    expect(item.backendSessionId).toBeUndefined();
  });

  it("enqueue carries userId and channel from the input", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, {
      text: "hi",
      userId: "u1",
      channel: "web",
    });

    const item = useMessageQueueStore.getState().getQueue(SESSION_ID)[0];
    expect(item.userId).toBe("u1");
    expect(item.channel).toBe("web");
  });

  // ---------------------------------------------------------------------------
  // remove / edit / reorder
  // ---------------------------------------------------------------------------

  it("remove drops the item with the matching id", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "keep" });
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "drop" });
    const queue = useMessageQueueStore.getState().getQueue(SESSION_ID);
    const targetId = queue[1].id;

    useMessageQueueStore.getState().remove(SESSION_ID, targetId);

    const next = useMessageQueueStore.getState().getQueue(SESSION_ID);
    expect(next).toHaveLength(1);
    expect(next[0].text).toBe("keep");
  });

  it("remove on an unknown id is a no-op", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    useMessageQueueStore.getState().remove(SESSION_ID, "does-not-exist");
    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)).toHaveLength(
      1,
    );
  });

  it("remove on an unknown session does not throw", () => {
    expect(() =>
      useMessageQueueStore.getState().remove("ghost", "x"),
    ).not.toThrow();
  });

  it("edit updates the text of the matching item only", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "a" });
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "b" });
    const idA = useMessageQueueStore.getState().getQueue(SESSION_ID)[0].id;

    useMessageQueueStore.getState().edit(SESSION_ID, idA, "edited");

    const queue = useMessageQueueStore.getState().getQueue(SESSION_ID);
    expect(queue[0].text).toBe("edited");
    expect(queue[1].text).toBe("b");
  });

  it("reorder replaces the entire item list for the session", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "a" });
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "b" });
    const reordered = [
      { ...useMessageQueueStore.getState().getQueue(SESSION_ID)[1] },
      { ...useMessageQueueStore.getState().getQueue(SESSION_ID)[0] },
    ];

    useMessageQueueStore.getState().reorder(SESSION_ID, reordered);

    const queue = useMessageQueueStore.getState().getQueue(SESSION_ID);
    expect(queue.map((i) => i.text)).toEqual(["b", "a"]);
  });

  // ---------------------------------------------------------------------------
  // clear
  // ---------------------------------------------------------------------------

  it("clear removes the session queue and its runState", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    useMessageQueueStore.getState().setRunState(SESSION_ID, "paused");

    useMessageQueueStore.getState().clear(SESSION_ID);

    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)).toEqual([]);
    expect(useMessageQueueStore.getState().getRunState(SESSION_ID)).toBe(
      "idle",
    );
    expect(localStorage.getItem(getStorageKey(SESSION_ID))).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // migrateQueue
  // ---------------------------------------------------------------------------

  it("migrateQueue moves items from source to destination and clears source", () => {
    useMessageQueueStore.getState().enqueue("src", { text: "s1" });
    useMessageQueueStore.getState().enqueue("dst", { text: "d1" });

    useMessageQueueStore.getState().migrateQueue("src", "dst");

    const dst = useMessageQueueStore.getState().getQueue("dst");
    const src = useMessageQueueStore.getState().getQueue("src");
    expect(dst.map((i) => i.text)).toEqual(["d1", "s1"]);
    expect(src).toEqual([]);
  });

  it("migrateQueue is a no-op when source and destination are the same", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });

    useMessageQueueStore.getState().migrateQueue(SESSION_ID, SESSION_ID);

    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)).toHaveLength(
      1,
    );
    expect(useMessageQueueStore.getState().lastMigratedTo).toBeNull();
  });

  it("migrateQueue sets lastMigratedTo to the destination", () => {
    useMessageQueueStore.getState().enqueue("src", { text: "s1" });

    useMessageQueueStore.getState().migrateQueue("src", "dst");

    expect(useMessageQueueStore.getState().lastMigratedTo).toBe("dst");
  });

  it("migrateQueue carries source runState to destination when destination has none", () => {
    useMessageQueueStore.getState().setRunState("src", "paused");

    useMessageQueueStore.getState().migrateQueue("src", "dst");

    expect(useMessageQueueStore.getState().getRunState("dst")).toBe("paused");
  });

  it("migrateQueue does not overwrite destination runState if already set", () => {
    useMessageQueueStore.getState().setRunState("src", "paused");
    useMessageQueueStore.getState().setRunState("dst", "running");

    useMessageQueueStore.getState().migrateQueue("src", "dst");

    expect(useMessageQueueStore.getState().getRunState("dst")).toBe("running");
  });

  // ---------------------------------------------------------------------------
  // setItemStatus
  // ---------------------------------------------------------------------------

  it("setItemStatus updates the status of the matching item", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    const id = useMessageQueueStore.getState().getQueue(SESSION_ID)[0].id;

    useMessageQueueStore.getState().setItemStatus(SESSION_ID, id, "sent");

    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)[0].status).toBe(
      "sent",
    );
  });

  it("setItemStatus to 'failed' increments retryCount and stores errorMessage", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    const id = useMessageQueueStore.getState().getQueue(SESSION_ID)[0].id;

    useMessageQueueStore
      .getState()
      .setItemStatus(SESSION_ID, id, "failed", "boom");

    const item = useMessageQueueStore.getState().getQueue(SESSION_ID)[0];
    expect(item.status).toBe("failed");
    expect(item.retryCount).toBe(1);
    expect(item.errorMessage).toBe("boom");
  });

  it("setItemStatus to a non-failed status does not increment retryCount", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    const id = useMessageQueueStore.getState().getQueue(SESSION_ID)[0].id;

    useMessageQueueStore.getState().setItemStatus(SESSION_ID, id, "sending");
    useMessageQueueStore.getState().setItemStatus(SESSION_ID, id, "sent");

    const item = useMessageQueueStore.getState().getQueue(SESSION_ID)[0];
    expect(item.retryCount).toBe(0);
  });

  // ---------------------------------------------------------------------------
  // setRunState / getRunState / persistToStorage
  // ---------------------------------------------------------------------------

  it("setRunState updates the runState and persists it with the items", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });

    useMessageQueueStore.getState().setRunState(SESSION_ID, "paused");

    expect(useMessageQueueStore.getState().getRunState(SESSION_ID)).toBe(
      "paused",
    );
    const parsed = JSON.parse(
      localStorage.getItem(getStorageKey(SESSION_ID)) as string,
    );
    expect(parsed.runState).toBe("paused");
  });

  it("setRunState with 'running' then 'idle' cycles the persisted state", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    useMessageQueueStore.getState().setRunState(SESSION_ID, "running");
    useMessageQueueStore.getState().setRunState(SESSION_ID, "idle");

    const parsed = JSON.parse(
      localStorage.getItem(getStorageKey(SESSION_ID)) as string,
    );
    expect(parsed.runState).toBe("idle");
  });

  // ---------------------------------------------------------------------------
  // setCurrentSendingId
  // ---------------------------------------------------------------------------

  it("setCurrentSendingId stores the id and can be cleared with null", () => {
    useMessageQueueStore.getState().setCurrentSendingId("abc");
    expect(useMessageQueueStore.getState().currentSendingId).toBe("abc");
    useMessageQueueStore.getState().setCurrentSendingId(null);
    expect(useMessageQueueStore.getState().currentSendingId).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // consumeMigratedTo
  // ---------------------------------------------------------------------------

  it("consumeMigratedTo returns the stored destination then resets to null", () => {
    useMessageQueueStore.getState().enqueue("src", { text: "s" });
    useMessageQueueStore.getState().migrateQueue("src", "dst");

    expect(useMessageQueueStore.getState().consumeMigratedTo()).toBe("dst");
    expect(useMessageQueueStore.getState().consumeMigratedTo()).toBeNull();
  });

  it("consumeMigratedTo returns null when no migration has happened", () => {
    expect(useMessageQueueStore.getState().consumeMigratedTo()).toBeNull();
  });

  // ---------------------------------------------------------------------------
  // persistToStorage / loadFromStorage
  // ---------------------------------------------------------------------------

  it("persistToStorage writes the current items + runState to localStorage", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    useMessageQueueStore.getState().setRunState(SESSION_ID, "paused");

    // Wipe storage then re-persist.
    localStorage.removeItem(getStorageKey(SESSION_ID));
    useMessageQueueStore.getState().persistToStorage(SESSION_ID);

    const parsed = JSON.parse(
      localStorage.getItem(getStorageKey(SESSION_ID)) as string,
    );
    expect(parsed.items).toHaveLength(1);
    expect(parsed.runState).toBe("paused");
  });

  it("loadFromStorage restores items and respects persisted 'paused' runState", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    useMessageQueueStore.getState().setRunState(SESSION_ID, "paused");

    resetStore();
    useMessageQueueStore.getState().loadFromStorage(SESSION_ID);

    const queue = useMessageQueueStore.getState().getQueue(SESSION_ID);
    expect(queue).toHaveLength(1);
    expect(queue[0].text).toBe("x");
    expect(useMessageQueueStore.getState().getRunState(SESSION_ID)).toBe(
      "paused",
    );
  });

  it("loadFromStorage resets a persisted non-paused runState to 'idle'", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "x" });
    useMessageQueueStore.getState().setRunState(SESSION_ID, "running");

    resetStore();
    useMessageQueueStore.getState().loadFromStorage(SESSION_ID);

    expect(useMessageQueueStore.getState().getRunState(SESSION_ID)).toBe(
      "idle",
    );
  });

  it("loadFromStorage clears stale in-memory state when no stored entry exists", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "stale" });

    removeQueueFromStorage(SESSION_ID);
    useMessageQueueStore.getState().loadFromStorage(SESSION_ID);

    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)).toEqual([]);
  });

  // ---------------------------------------------------------------------------
  // applyRemoteItems / applyRemoteRunState
  // ---------------------------------------------------------------------------

  it("applyRemoteItems replaces the in-memory queue for the session", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "local" });
    const remote = [
      {
        id: "remote-1",
        text: "remote",
        status: "pending" as const,
        retryCount: 0,
        createdAt: 1,
      },
    ];

    useMessageQueueStore.getState().applyRemoteItems(SESSION_ID, remote);

    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)).toEqual(
      remote,
    );
  });

  it("applyRemoteItems with an empty list deletes the session queue", () => {
    useMessageQueueStore.getState().enqueue(SESSION_ID, { text: "local" });

    useMessageQueueStore.getState().applyRemoteItems(SESSION_ID, []);

    expect(useMessageQueueStore.getState().getQueue(SESSION_ID)).toEqual([]);
    expect(SESSION_ID in useMessageQueueStore.getState().queues).toBe(false);
  });

  it("applyRemoteRunState sets the runState without broadcasting", () => {
    useMessageQueueStore.getState().applyRemoteRunState(SESSION_ID, "error");

    expect(useMessageQueueStore.getState().getRunState(SESSION_ID)).toBe(
      "error",
    );
  });

  // ---------------------------------------------------------------------------
  // withSendLock — falls back to direct execution in jsdom (no navigator.locks)
  // ---------------------------------------------------------------------------

  it("withSendLock runs the callback and returns its result when Web Locks is unavailable", async () => {
    // jsdom does not implement navigator.locks, so this exercises the fallback path.
    const result = await withSendLock(SESSION_ID, () => "done");
    expect(result).toBe("done");
  });

  it("withSendLock propagates async results through the fallback path", async () => {
    const result = await withSendLock(SESSION_ID, async () => 42);
    expect(result).toBe(42);
  });

  // ---------------------------------------------------------------------------
  // holdOwnershipLock — fires onAcquired immediately when Web Locks unavailable
  // ---------------------------------------------------------------------------

  it("holdOwnershipLock calls onAcquired synchronously when Web Locks is unavailable", async () => {
    const onAcquired = vi.fn();
    const controller = new AbortController();

    await holdOwnershipLock(SESSION_ID, onAcquired, controller.signal);

    expect(onAcquired).toHaveBeenCalled();
    controller.abort();
  });
});
