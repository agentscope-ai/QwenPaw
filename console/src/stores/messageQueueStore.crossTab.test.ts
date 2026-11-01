import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  STORAGE_PREFIX,
  getStorageKey,
  useMessageQueueStore,
  type QueueItem,
} from "./messageQueueStore";

// The store registers its cross-tab listeners once, at module import time:
// one on the shared "qwenpaw:queue" BroadcastChannel and one on window for
// "storage" events. These suites drive both listeners from the outside, the
// same way a second browser tab would, and assert on the in-memory state that
// the handlers are contractually allowed to touch (they must never re-write
// storage or re-broadcast, which would loop).

const CHANNEL_NAME = "qwenpaw:queue";

/**
 * BroadcastChannel delivery is queued as a macrotask by the platform, so a
 * plain microtask flush is not enough. Yield a few macrotask turns instead of
 * sleeping a fixed duration, which keeps the suite both fast and stable.
 */
function flushChannel(turns = 4): Promise<void> {
  return new Promise((resolve) => {
    let remaining = turns;
    const tick = () => {
      remaining -= 1;
      if (remaining <= 0) resolve();
      else setTimeout(tick, 0);
    };
    setTimeout(tick, 0);
  });
}

function makeItem(id: string, extra: Partial<QueueItem> = {}): QueueItem {
  return {
    id,
    text: `text-${id}`,
    status: "pending",
    retryCount: 0,
    createdAt: 1,
    ...extra,
  };
}

function resetStore() {
  useMessageQueueStore.setState({
    queues: {},
    runStates: {},
    currentSendingId: null,
    lastMigratedTo: null,
  });
}

function clearStorage() {
  localStorage.clear();
  try {
    sessionStorage.clear();
  } catch {
    // jsdom may reject sessionStorage access in some configurations
  }
}

/** Post a payload from a throwaway peer channel that shares the store's name. */
async function postFromPeer(payload: unknown) {
  const peer = new BroadcastChannel(CHANNEL_NAME);
  peer.postMessage(payload);
  await flushChannel();
  peer.close();
}

/** Dispatch a synthetic cross-tab storage event on window. */
function dispatchStorage(key: string | null, newValue: string | null) {
  window.dispatchEvent(new StorageEvent("storage", { key, newValue }));
}

describe("messageQueueStore cross-tab BroadcastChannel listener", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  afterEach(() => {
    resetStore();
    clearStorage();
  });

  it("applies a migrate payload to both source and destination", async () => {
    const sourceItems = [makeItem("src-1")];
    const destItems = [makeItem("dest-1")];

    await postFromPeer({
      type: "migrate",
      sessionId: "sess-src",
      sourceItems,
      toSessionId: "sess-dest",
      items: destItems,
      runState: "paused",
    });

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-src")).toEqual(sourceItems);
    expect(store.getQueue("sess-dest")).toEqual(destItems);
    expect(store.getRunState("sess-dest")).toBe("paused");
  });

  it("applies migrate source items even when the destination is absent", async () => {
    const sourceItems = [makeItem("src-only")];

    await postFromPeer({
      type: "migrate",
      sessionId: "sess-src",
      sourceItems,
    });

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-src")).toEqual(sourceItems);
    expect(store.getQueue("sess-other")).toEqual([]);
  });

  it("treats a missing sourceItems list on migrate as an empty source queue", async () => {
    useMessageQueueStore.setState({
      queues: { "sess-src": [makeItem("old")] },
    });

    await postFromPeer({
      type: "migrate",
      sessionId: "sess-src",
      toSessionId: "sess-dest",
      items: [makeItem("new")],
    });

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-src")).toEqual([]);
    expect(store.getQueue("sess-dest").map((item) => item.id)).toEqual(["new"]);
  });

  it("skips the destination run state when a migrate payload omits it", async () => {
    await postFromPeer({
      type: "migrate",
      sessionId: "sess-src",
      sourceItems: [],
      toSessionId: "sess-dest",
      items: [makeItem("dest-2")],
    });

    const store = useMessageQueueStore.getState();
    expect(store.getRunState("sess-dest")).toBe("idle");
    expect(store.getQueue("sess-dest").map((item) => item.id)).toEqual([
      "dest-2",
    ]);
  });

  it("applies a runState-only payload without touching any queue", async () => {
    useMessageQueueStore.setState({
      queues: { "sess-rs": [makeItem("keep")] },
    });

    await postFromPeer({
      type: "runState",
      sessionId: "sess-rs",
      runState: "error",
    });

    const store = useMessageQueueStore.getState();
    expect(store.getRunState("sess-rs")).toBe("error");
    expect(store.getQueue("sess-rs").map((item) => item.id)).toEqual(["keep"]);
  });

  it("ignores a runState payload that carries no run state", async () => {
    await postFromPeer({ type: "runState", sessionId: "sess-rs2" });

    expect(useMessageQueueStore.getState().getRunState("sess-rs2")).toBe(
      "idle",
    );
  });

  it("applies a generic payload carrying both items and run state", async () => {
    const items = [makeItem("gen-1", { status: "sending" })];

    await postFromPeer({
      type: "setItemStatus",
      sessionId: "sess-gen",
      items,
      runState: "running",
    });

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-gen")).toEqual(items);
    expect(store.getRunState("sess-gen")).toBe("running");
  });

  it("applies a generic payload that carries only items", async () => {
    await postFromPeer({
      type: "reorder",
      sessionId: "sess-items",
      items: [makeItem("only-items")],
    });

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-items").map((item) => item.id)).toEqual([
      "only-items",
    ]);
    expect(store.getRunState("sess-items")).toBe("idle");
  });

  it("applies a generic payload that carries only a run state", async () => {
    await postFromPeer({
      type: "clear",
      sessionId: "sess-rs3",
      runState: "idle",
    });

    expect(useMessageQueueStore.getState().getRunState("sess-rs3")).toBe(
      "idle",
    );
    expect(useMessageQueueStore.getState().getQueue("sess-rs3")).toEqual([]);
  });

  it("ignores payloads that are not objects", async () => {
    useMessageQueueStore.setState({
      queues: { "sess-guard": [makeItem("untouched")] },
    });

    await postFromPeer(null);
    await postFromPeer("not-an-object");
    await postFromPeer(undefined);

    expect(
      useMessageQueueStore
        .getState()
        .getQueue("sess-guard")
        .map((i) => i.id),
    ).toEqual(["untouched"]);
  });

  it("does not re-broadcast or re-write storage when applying remote state", async () => {
    const peer = new BroadcastChannel(CHANNEL_NAME);
    const echoed: unknown[] = [];
    peer.addEventListener("message", (event) => echoed.push(event.data));

    peer.postMessage({
      type: "runState",
      sessionId: "sess-loop",
      runState: "paused",
    });
    await flushChannel();

    expect(echoed).toEqual([]);
    expect(localStorage.getItem(getStorageKey("sess-loop"))).toBeNull();
    peer.close();
  });
});

describe("messageQueueStore cross-tab storage listener", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  afterEach(() => {
    resetStore();
    clearStorage();
  });

  it("clears the in-memory queue when another tab removes the key", () => {
    useMessageQueueStore.setState({
      queues: { "sess-removed": [makeItem("gone")] },
    });

    dispatchStorage(getStorageKey("sess-removed"), null);

    expect(useMessageQueueStore.getState().getQueue("sess-removed")).toEqual(
      [],
    );
  });

  it("applies persisted items and a paused run state from another tab", () => {
    const items = [makeItem("persisted-1")];

    dispatchStorage(
      getStorageKey("sess-persisted"),
      JSON.stringify({ items, runState: "paused" }),
    );

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-persisted")).toEqual(items);
    expect(store.getRunState("sess-persisted")).toBe("paused");
  });

  it("applies an error run state from another tab", () => {
    dispatchStorage(
      getStorageKey("sess-err"),
      JSON.stringify({ items: [makeItem("e1")], runState: "error" }),
    );

    expect(useMessageQueueStore.getState().getRunState("sess-err")).toBe(
      "error",
    );
  });

  it("keeps the run state untouched when the persisted one is not paused or error", () => {
    dispatchStorage(
      getStorageKey("sess-running"),
      JSON.stringify({ items: [makeItem("r1")], runState: "running" }),
    );

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-running").map((item) => item.id)).toEqual([
      "r1",
    ]);
    expect(store.getRunState("sess-running")).toBe("idle");
  });

  it("accepts the legacy bare-array persistence shape", () => {
    const items = [makeItem("legacy-1")];

    dispatchStorage(getStorageKey("sess-legacy"), JSON.stringify(items));

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-legacy")).toEqual(items);
    expect(store.getRunState("sess-legacy")).toBe("idle");
  });

  it("falls back to an empty item list when the persisted object has none", () => {
    dispatchStorage(
      getStorageKey("sess-noitems"),
      JSON.stringify({ runState: "paused" }),
    );

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-noitems")).toEqual([]);
    expect(store.getRunState("sess-noitems")).toBe("paused");
  });

  it("ignores keys outside the queue storage prefix", () => {
    useMessageQueueStore.setState({
      queues: { "sess-safe": [makeItem("safe")] },
    });

    dispatchStorage(
      "some-other-key",
      JSON.stringify({ items: [], runState: "paused" }),
    );
    dispatchStorage(null, null);
    dispatchStorage("", null);

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-safe").map((item) => item.id)).toEqual([
      "safe",
    ]);
    expect(store.getRunState("some-other-key")).toBe("idle");
  });

  it("swallows malformed JSON written by another tab", () => {
    useMessageQueueStore.setState({
      queues: { "sess-bad": [makeItem("still-here")] },
    });

    dispatchStorage(getStorageKey("sess-bad"), "{not-json");

    expect(
      useMessageQueueStore
        .getState()
        .getQueue("sess-bad")
        .map((i) => i.id),
    ).toEqual(["still-here"]);
  });

  it("derives the session id by stripping only the storage prefix", () => {
    dispatchStorage(
      `${STORAGE_PREFIX}sess-with:colon`,
      JSON.stringify({ items: [makeItem("c1")], runState: "idle" }),
    );

    expect(
      useMessageQueueStore.getState().getQueue("sess-with:colon").length,
    ).toBe(1);
  });
});

describe("messageQueueStore legacy storage read paths", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  afterEach(() => {
    resetStore();
    clearStorage();
  });

  it("migrates a queue left in sessionStorage by an older build", () => {
    const key = getStorageKey("sess-session-migrated");
    const item = makeItem("from-session-storage");
    sessionStorage.setItem(
      key,
      JSON.stringify({ items: [item], runState: "paused" }),
    );

    useMessageQueueStore.getState().loadFromStorage("sess-session-migrated");

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-session-migrated").map((i) => i.id)).toEqual([
      "from-session-storage",
    ]);
    // The one-time migration moves the payload into localStorage and drops the
    // sessionStorage copy, so later reads never pay for it again.
    expect(localStorage.getItem(key)).not.toBeNull();
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it("reads the deprecated bare-array payload from localStorage", () => {
    const item = makeItem("array-shaped", { agentId: "agent-a" });
    localStorage.setItem(getStorageKey("sess-array"), JSON.stringify([item]));

    useMessageQueueStore.getState().loadFromStorage("sess-array");

    const store = useMessageQueueStore.getState();
    expect(store.getQueue("sess-array")).toEqual([item]);
    // A bare array carries no run state, so the session defaults to idle.
    expect(store.getRunState("sess-array")).toBe("idle");
  });

  it("leaves bizParams untouched on the deprecated bare-array payload", () => {
    // Identity restoration is documented as reading main's SDK 1.2 queue
    // shape, which is the object payload. A bare array predates that shape, so
    // its items are taken as-is and no field is promoted out of bizParams.
    const item = makeItem("array-identity", {
      bizParams: { session_id: "backend-1", user_id: "u-1", channel: "web" },
    });
    localStorage.setItem(
      getStorageKey("sess-array-id"),
      JSON.stringify([item]),
    );

    useMessageQueueStore.getState().loadFromStorage("sess-array-id");

    expect(
      useMessageQueueStore.getState().getQueue("sess-array-id")[0],
    ).toEqual(item);
  });

  it("promotes the captured identity out of bizParams on the object payload", () => {
    // Contrast case for the one above: the object payload is the SDK 1.2 shape
    // that identity restoration targets, so the snapshot fields are promoted.
    const item = makeItem("object-identity", {
      backendSessionId: "already-set",
      bizParams: { session_id: "backend-2", user_id: "u-2", channel: "api" },
    });
    localStorage.setItem(
      getStorageKey("sess-object-id"),
      JSON.stringify({ items: [item], runState: "idle" }),
    );

    useMessageQueueStore.getState().loadFromStorage("sess-object-id");

    const restored = useMessageQueueStore
      .getState()
      .getQueue("sess-object-id")[0];
    // An explicitly captured field wins over the snapshot.
    expect(restored.backendSessionId).toBe("already-set");
    expect(restored.userId).toBe("u-2");
    expect(restored.channel).toBe("api");
  });
});

describe("messageQueueStore pure helper edge cases", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  afterEach(() => {
    resetStore();
    clearStorage();
  });

  it("keeps the first session when two queued items share a timestamp", async () => {
    const { getLatestQueuedSessionIdForAgent } = await import(
      "./messageQueueStore"
    );
    const tied = 1_700_000_000_000;

    const latest = getLatestQueuedSessionIdForAgent(
      {
        "sess-a": [makeItem("a1", { agentId: "agent-x", createdAt: tied })],
        "sess-b": [makeItem("b1", { agentId: "agent-x", createdAt: tied })],
      },
      "agent-x",
    );

    // Ties must not replace the incumbent: the comparison is "<=", so the
    // earliest session seen keeps winning deterministically.
    expect(latest).toBe("sess-a");
  });

  it("prefers the strictly newer item across sessions", async () => {
    const { getLatestQueuedSessionIdForAgent } = await import(
      "./messageQueueStore"
    );

    const latest = getLatestQueuedSessionIdForAgent(
      {
        "sess-old": [makeItem("o1", { agentId: "agent-y", createdAt: 10 })],
        "sess-new": [makeItem("n1", { agentId: "agent-y", createdAt: 20 })],
      },
      "agent-y",
    );

    expect(latest).toBe("sess-new");
  });

  it("leaves the store untouched when migrating with an agent id that owns nothing", () => {
    const store = useMessageQueueStore.getState();
    store.enqueue("sess-mig-from", { text: "kept", agentId: "agent-owner" });
    const before = useMessageQueueStore.getState();

    before.migrateQueue("sess-mig-from", "sess-mig-to", "agent-stranger");

    const after = useMessageQueueStore.getState();
    // No item moved and no run state existed, so the reducer returns the very
    // same state object rather than a clone.
    expect(after.queues).toBe(before.queues);
    expect(after.getQueue("sess-mig-from").map((i) => i.text)).toEqual([
      "kept",
    ]);
    expect(after.getQueue("sess-mig-to")).toEqual([]);
    expect(store).toBeTruthy();
  });

  it("clears a stale error run state once reconciliation drops the failed item", () => {
    const store = useMessageQueueStore.getState();
    store.enqueue("sess-recon", { text: "sent one", agentId: "agent-r" });
    store.enqueue("sess-recon", { text: "still queued", agentId: "agent-r" });
    const queued = useMessageQueueStore.getState().getQueue("sess-recon");
    store.setItemStatus("sess-recon", queued[0].id, "failed", "boom");
    store.setRunState("sess-recon", "error");

    useMessageQueueStore.getState().reconcileHistory("sess-recon", "agent-r", [
      {
        role: "user",
        metadata: {
          qwenpaw_client_message_id: queued[0].clientMessageId as string,
        },
      },
    ]);

    const after = useMessageQueueStore.getState();
    expect(after.getQueue("sess-recon").map((i) => i.text)).toEqual([
      "still queued",
    ]);
    // The only failed item is gone, so "error" is no longer justified.
    expect(after.getRunState("sess-recon")).toBe("idle");
  });

  it("keeps an error run state while a failed item is still queued", () => {
    const store = useMessageQueueStore.getState();
    store.enqueue("sess-recon2", { text: "failed one", agentId: "agent-r2" });
    store.enqueue("sess-recon2", { text: "acked one", agentId: "agent-r2" });
    const queued = useMessageQueueStore.getState().getQueue("sess-recon2");
    store.setItemStatus("sess-recon2", queued[0].id, "failed", "boom");
    store.setRunState("sess-recon2", "error");

    useMessageQueueStore
      .getState()
      .reconcileHistory("sess-recon2", "agent-r2", [
        {
          role: "user",
          metadata: {
            qwenpaw_client_message_id: queued[1].clientMessageId as string,
          },
        },
      ]);

    const after = useMessageQueueStore.getState();
    expect(after.getQueue("sess-recon2").map((i) => i.text)).toEqual([
      "failed one",
    ]);
    expect(after.getRunState("sess-recon2")).toBe("error");
  });
});
