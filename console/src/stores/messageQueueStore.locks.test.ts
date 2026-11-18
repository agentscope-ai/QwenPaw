import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  findQueueItemSessionId,
  getQueueKey,
  getStorageKey,
  holdOwnershipLock,
  recoverLegacyDraftQueue,
  useMessageQueueStore,
  withAvailableOwnershipLock,
  withSendLock,
  type QueueItem,
} from "./messageQueueStore";

// jsdom implements neither the Web Locks API nor a BroadcastChannel that can be
// made unavailable on demand, so the lock-backed branches of this store are
// driven through an injected `navigator.locks` stub. Every stub is removed in
// afterEach so the fallback suites elsewhere keep seeing the real jsdom shape.

type LockRequest = (...args: unknown[]) => Promise<unknown>;

const NAV_LOCKS_KEY = "locks";

interface StubLocks {
  request: ReturnType<typeof vi.fn>;
}

/** Install a `navigator.locks` stub whose request resolves with `lockValue`. */
function installLocks(request: LockRequest): StubLocks {
  const stub: StubLocks = { request: vi.fn(request) };
  Object.defineProperty(navigator, NAV_LOCKS_KEY, {
    configurable: true,
    value: stub,
  });
  return stub;
}

/** Remove the stub so `getLockManager()` reports the API as absent again. */
function removeLocks() {
  // `navigator` may have been stubbed away entirely by a sibling suite, and
  // unstubAllGlobals() may already have restored it, so guard both ways.
  if (typeof navigator === "undefined") return;
  Object.defineProperty(navigator, NAV_LOCKS_KEY, {
    configurable: true,
    value: undefined,
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

afterEach(() => {
  removeLocks();
  vi.unstubAllGlobals();
  vi.resetModules();
  resetStore();
  clearStorage();
});

describe("messageQueueStore Web Locks send path", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  it("returns null from withSendLock when the lock is unavailable", async () => {
    // A falsy lock means another tab holds it, so the sender must back off
    // rather than run the callback.
    const fn = vi.fn(() => "should-not-run");
    installLocks((_name, _opts, callback) =>
      (callback as (lock: unknown) => Promise<unknown>)(null),
    );

    const result = await withSendLock("sess-send", fn);

    expect(result).toBeNull();
    expect(fn).not.toHaveBeenCalled();
  });

  it("runs the callback and returns its value when the send lock is granted", async () => {
    const lock = { name: "granted" };
    installLocks((_name, _opts, callback) =>
      (callback as (l: unknown) => Promise<unknown>)(lock),
    );

    const result = await withSendLock("sess-send-ok", async () => "sent");

    expect(result).toBe("sent");
  });

  it("requests the send lock under the per-session name with ifAvailable", async () => {
    const stub = installLocks((_n, _o, callback) =>
      (callback as (l: unknown) => Promise<unknown>)({ ok: true }),
    );

    await withSendLock("sess-named", () => 1);

    expect(stub.request).toHaveBeenCalledTimes(1);
    const [name, options] = stub.request.mock.calls[0] as [string, object];
    expect(name).toBe("qwenpaw:queue-send:sess-named");
    expect(options).toEqual({ ifAvailable: true });
  });

  it("swallows a rejected send lock request", async () => {
    installLocks(() => Promise.reject(new Error("locks-broken")));

    const result = await withSendLock("sess-reject", () => "unreachable");

    // A failing lock manager must never surface as a send error.
    expect(result).toBeNull();
  });
});

describe("messageQueueStore Web Locks ownership path", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  it("returns null when the foreground owner holds the lock", async () => {
    const fn = vi.fn(() => "should-not-run");
    installLocks((_n, _o, callback) =>
      (callback as (l: unknown) => Promise<unknown>)(null),
    );

    const result = await withAvailableOwnershipLock("sess-owned", fn);

    expect(result).toBeNull();
    expect(fn).not.toHaveBeenCalled();
  });

  it("does not run the callback when the signal aborts before the grant", async () => {
    const fn = vi.fn(() => "should-not-run");
    const controller = new AbortController();
    // Abort while the lock is being granted: the entry guard has already passed
    // (the signal was live on entry), so the callback itself must re-check.
    installLocks((_n, _o, callback) => {
      controller.abort();
      return (callback as (l: unknown) => Promise<unknown>)({ granted: true });
    });

    const result = await withAvailableOwnershipLock(
      "sess-abort-mid",
      fn,
      controller.signal,
    );

    expect(result).toBeNull();
    expect(fn).not.toHaveBeenCalled();
  });

  it("runs the callback when ownership is free", async () => {
    installLocks((_n, _o, callback) =>
      (callback as (l: unknown) => Promise<unknown>)({ granted: true }),
    );

    const result = await withAvailableOwnershipLock("sess-free", () => 7);

    expect(result).toBe(7);
  });

  it("requests ownership as exclusive and non-blocking", async () => {
    const stub = installLocks((_n, _o, callback) =>
      (callback as (l: unknown) => Promise<unknown>)({ granted: true }),
    );

    await withAvailableOwnershipLock("sess-opts", () => 1);

    const [name, options] = stub.request.mock.calls[0] as [string, object];
    expect(name).toBe("qwenpaw:queue-owner:sess-opts");
    expect(options).toEqual({ mode: "exclusive", ifAvailable: true });
  });

  it("swallows a rejected ownership request", async () => {
    installLocks(() => Promise.reject(new Error("owner-broken")));

    const result = await withAvailableOwnershipLock("sess-own-reject", () => 1);

    expect(result).toBeNull();
  });
});

describe("messageQueueStore holdOwnershipLock with Web Locks present", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  it("does nothing when the granted lock is falsy", async () => {
    const onAcquired = vi.fn();
    const controller = new AbortController();
    installLocks((_n, _o, callback) =>
      (callback as (l: unknown) => Promise<void>)(null),
    );

    await holdOwnershipLock("sess-hold-null", onAcquired, controller.signal);

    expect(onAcquired).not.toHaveBeenCalled();
  });

  it("releases without acquiring when the signal is already aborted", async () => {
    const onAcquired = vi.fn();
    const controller = new AbortController();
    installLocks((_n, _o, callback) =>
      (callback as (l: unknown) => Promise<void>)({ held: true }),
    );
    controller.abort();

    await holdOwnershipLock("sess-hold-aborted", onAcquired, controller.signal);

    expect(onAcquired).not.toHaveBeenCalled();
  });

  it("holds the lock until the caller aborts", async () => {
    const onAcquired = vi.fn();
    const controller = new AbortController();
    installLocks((_n, _o, callback) =>
      (callback as (l: unknown) => Promise<void>)({ held: true }),
    );

    const holding = holdOwnershipLock(
      "sess-hold-until-abort",
      onAcquired,
      controller.signal,
    );
    // Ownership is announced synchronously once the lock is granted.
    expect(onAcquired).toHaveBeenCalledTimes(1);
    controller.abort();
    await expect(holding).resolves.toBeUndefined();
  });

  it("resolves immediately when the acquire callback itself aborts", async () => {
    const controller = new AbortController();
    // The owner may abort from inside onAcquired (for example when it decides
    // another tab should take over), which the hold loop must notice at once
    // instead of waiting for an abort event that will never fire.
    const onAcquired = vi.fn(() => controller.abort());
    installLocks((_n, _o, callback) =>
      (callback as (l: unknown) => Promise<void>)({ held: true }),
    );

    await expect(
      holdOwnershipLock("sess-hold-self-abort", onAcquired, controller.signal),
    ).resolves.toBeUndefined();
    expect(onAcquired).toHaveBeenCalledTimes(1);
  });

  it("requests the ownership lock exclusively with the abort signal", async () => {
    const controller = new AbortController();
    const stub = installLocks((_n, _o, callback) => {
      controller.abort();
      return (callback as (l: unknown) => Promise<void>)({ held: true });
    });

    await holdOwnershipLock("sess-hold-opts", vi.fn(), controller.signal);

    const [name, options] = stub.request.mock.calls[0] as [string, object];
    expect(name).toBe("qwenpaw:queue-owner:sess-hold-opts");
    expect(options).toEqual({ mode: "exclusive", signal: controller.signal });
  });

  it("resolves undefined when the lock request rejects", async () => {
    const onAcquired = vi.fn();
    const controller = new AbortController();
    installLocks(() => Promise.reject(new Error("hold-broken")));

    await expect(
      holdOwnershipLock("sess-hold-reject", onAcquired, controller.signal),
    ).resolves.toBeUndefined();
    expect(onAcquired).not.toHaveBeenCalled();
  });
});

describe("messageQueueStore recoverLegacyDraftQueue guards", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  it("ignores a queue key that is not a draft key", async () => {
    const request = vi.fn();
    installLocks(request as unknown as LockRequest);
    const store = useMessageQueueStore.getState();
    store.enqueue("new:agent-a", { text: "draft", agentId: "agent-a" });

    await recoverLegacyDraftQueue("chat-real-id");

    // Nothing is migrated and no lock is taken for a real chat id.
    expect(request).not.toHaveBeenCalled();
    expect(useMessageQueueStore.getState().getQueue("chat-real-id")).toEqual(
      [],
    );
    expect(useMessageQueueStore.getState().getQueue("new:agent-a").length).toBe(
      1,
    );
  });

  it("ignores a draft key when no legacy source queue holds items", async () => {
    const request = vi.fn();
    installLocks(request as unknown as LockRequest);

    await recoverLegacyDraftQueue(getQueueKey("agent-empty"));

    expect(request).not.toHaveBeenCalled();
    expect(
      useMessageQueueStore.getState().getQueue(getQueueKey("agent-empty")),
    ).toEqual([]);
  });

  it("skips recovery when the signal is already aborted", async () => {
    // Without Web Locks the recovery runs inline, so the abort guard inside it
    // is the only thing preventing a migration after unmount.
    removeLocks();
    const controller = new AbortController();
    controller.abort();
    const store = useMessageQueueStore.getState();
    store.enqueue("new:agent-ab", { text: "draft", agentId: "agent-ab" });

    await recoverLegacyDraftQueue(getQueueKey("agent-ab"), controller.signal);

    expect(
      useMessageQueueStore.getState().getQueue("new:agent-ab").length,
    ).toBe(1);
    expect(
      useMessageQueueStore.getState().getQueue(getQueueKey("agent-ab")),
    ).toEqual([]);
  });

  it("migrates the legacy queue through the exclusive migration lock", async () => {
    const seen: unknown[] = [];
    const stub = installLocks((name, options, callback) => {
      seen.push(name, options);
      return (callback as () => Promise<void>)();
    });
    const store = useMessageQueueStore.getState();
    store.enqueue("new:agent-lk", { text: "draft", agentId: "agent-lk" });

    await recoverLegacyDraftQueue(getQueueKey("agent-lk"));

    expect(stub.request).toHaveBeenCalledTimes(1);
    expect(seen[0]).toBe("qwenpaw:queue-migrate:legacy-new");
    expect(seen[1]).toEqual({ mode: "exclusive", signal: undefined });
    const after = useMessageQueueStore.getState();
    expect(after.getQueue(getQueueKey("agent-lk")).map((i) => i.text)).toEqual([
      "draft",
    ]);
    expect(after.getQueue("new:agent-lk")).toEqual([]);
  });

  it("passes the abort signal through to the migration lock request", async () => {
    const controller = new AbortController();
    const stub = installLocks((_n, _o, callback) =>
      (callback as () => Promise<void>)(),
    );
    const store = useMessageQueueStore.getState();
    store.enqueue("new:agent-sig", { text: "draft", agentId: "agent-sig" });

    await recoverLegacyDraftQueue(getQueueKey("agent-sig"), controller.signal);

    const [, options] = stub.request.mock.calls[0] as [string, object];
    expect(options).toEqual({ mode: "exclusive", signal: controller.signal });
  });

  it("rethrows a migration lock failure when the signal is live", async () => {
    removeLocks();
    installLocks(() => Promise.reject(new Error("migrate-broken")));
    const store = useMessageQueueStore.getState();
    store.enqueue("new:agent-thr", { text: "draft", agentId: "agent-thr" });

    await expect(
      recoverLegacyDraftQueue(getQueueKey("agent-thr")),
    ).rejects.toThrow("migrate-broken");
  });

  it("swallows a migration lock failure once the caller aborted", async () => {
    removeLocks();
    const controller = new AbortController();
    installLocks(() => {
      controller.abort();
      return Promise.reject(new Error("migrate-cancelled"));
    });
    const store = useMessageQueueStore.getState();
    store.enqueue("new:agent-sw", { text: "draft", agentId: "agent-sw" });

    await expect(
      recoverLegacyDraftQueue(getQueueKey("agent-sw"), controller.signal),
    ).resolves.toBeUndefined();
  });
});

describe("messageQueueStore reconcileHistory early exits", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  it("returns untouched when no history message carries a receipt", () => {
    const store = useMessageQueueStore.getState();
    store.enqueue("sess-noack", { text: "queued", agentId: "agent-n" });
    const before = useMessageQueueStore.getState();

    before.reconcileHistory("sess-noack", "agent-n", [
      { role: "assistant", metadata: { qwenpaw_client_message_id: "x" } },
      { role: "user" },
      { role: "user", metadata: null },
    ]);

    const after = useMessageQueueStore.getState();
    expect(after.getQueue("sess-noack").map((i) => i.text)).toEqual(["queued"]);
    expect(after.runStates).toBe(before.runStates);
  });

  it("returns untouched when no queued item matches an acknowledged receipt", () => {
    const store = useMessageQueueStore.getState();
    store.enqueue("sess-nomatch", { text: "queued", agentId: "agent-m" });
    const before = useMessageQueueStore.getState();

    before.reconcileHistory("sess-nomatch", "agent-m", [
      { role: "user", metadata: { qwenpaw_client_message_id: "someone-else" } },
    ]);

    const after = useMessageQueueStore.getState();
    expect(after.getQueue("sess-nomatch").map((i) => i.text)).toEqual([
      "queued",
    ]);
    // Filtering removed nothing, so the reducer must not have rewritten state.
    expect(after.queues).toBe(before.queues);
  });

  it("keeps an item queued by a different agent even when its receipt is acked", () => {
    const store = useMessageQueueStore.getState();
    store.enqueue("sess-otheragent", { text: "other", agentId: "agent-z" });
    const queued = useMessageQueueStore.getState().getQueue("sess-otheragent");

    useMessageQueueStore
      .getState()
      .reconcileHistory("sess-otheragent", "agent-y", [
        {
          role: "user",
          metadata: {
            qwenpaw_client_message_id: queued[0].clientMessageId as string,
          },
        },
      ]);

    // Ownership guard: another agent's queued text must survive reconciliation.
    expect(
      useMessageQueueStore.getState().getQueue("sess-otheragent").length,
    ).toBe(1);
  });

  it("reads the queued items from storage when memory holds none", () => {
    const item = makeItem("stored-only", {
      clientMessageId: "cmid-stored",
      agentId: "agent-s",
    });
    localStorage.setItem(
      getStorageKey("sess-fromstorage"),
      JSON.stringify({ items: [item], runState: "idle" }),
    );

    useMessageQueueStore
      .getState()
      .reconcileHistory("sess-fromstorage", "agent-s", [
        {
          role: "user",
          metadata: { qwenpaw_client_message_id: "cmid-stored" },
        },
      ]);

    expect(
      useMessageQueueStore.getState().getQueue("sess-fromstorage"),
    ).toEqual([]);
  });

  it("never drops an item that has no client message id", () => {
    // An item without a receipt cannot be matched against backend history, so
    // reconciliation must keep it even while a sibling is acked and removed.
    const acked = makeItem("acked", {
      clientMessageId: "cmid-acked",
      agentId: "agent-c",
    });
    const noReceipt = makeItem("no-cmid", { agentId: "agent-c" });
    localStorage.setItem(
      getStorageKey("sess-nocmid"),
      JSON.stringify({ items: [acked, noReceipt], runState: "idle" }),
    );

    useMessageQueueStore
      .getState()
      .reconcileHistory("sess-nocmid", "agent-c", [
        { role: "user", metadata: { qwenpaw_client_message_id: "cmid-acked" } },
      ]);

    expect(
      useMessageQueueStore
        .getState()
        .getQueue("sess-nocmid")
        .map((i) => i.id),
    ).toEqual(["no-cmid"]);
  });
});

describe("messageQueueStore findQueueItemSessionId lookup", () => {
  beforeEach(() => {
    resetStore();
    clearStorage();
  });

  it("returns the preferred session when it really holds the item", () => {
    const item = makeItem("target");

    const found = findQueueItemSessionId(
      { "sess-pref": [item], "sess-other": [makeItem("other")] },
      "target",
      "sess-pref",
    );

    expect(found).toBe("sess-pref");
  });

  it("does not short-circuit on a preferred session that lacks the item", () => {
    const found = findQueueItemSessionId(
      { "sess-pref": [makeItem("a")], "sess-real": [makeItem("b")] },
      "b",
      "sess-pref",
    );

    expect(found).toBe("sess-real");
  });

  it("falls back to scanning every queue when no preference is given", () => {
    const found = findQueueItemSessionId(
      { "sess-x": [makeItem("x1")], "sess-y": [makeItem("y1")] },
      "y1",
    );

    expect(found).toBe("sess-y");
  });

  it("returns undefined when no queue holds the item", () => {
    const found = findQueueItemSessionId(
      { "sess-x": [makeItem("x1")] },
      "missing",
      "sess-x",
    );

    expect(found).toBeUndefined();
  });
});

describe("messageQueueStore channel and lock manager environment guards", () => {
  // These three suites exercise the module-level environment probes, which are
  // only reachable by importing a fresh copy of the store under a stubbed
  // global. Each one restores the globals afterwards (see the file-level
  // afterEach) so no other suite observes the stub.

  it("silently skips broadcasting when BroadcastChannel is absent", async () => {
    vi.stubGlobal("BroadcastChannel", undefined);
    vi.resetModules();

    const mod = await import("./messageQueueStore");
    mod.useMessageQueueStore.getState().enqueue("sess-no-bc", { text: "hi" });

    // With no channel the queue must still work locally.
    expect(
      mod.useMessageQueueStore.getState().getQueue("sess-no-bc").length,
    ).toBe(1);
  });

  it("survives a BroadcastChannel constructor that throws", async () => {
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        constructor() {
          throw new Error("channel-unavailable");
        }
      },
    );
    vi.resetModules();

    const mod = await import("./messageQueueStore");
    mod.useMessageQueueStore
      .getState()
      .enqueue("sess-bc-throws", { text: "hi" });

    expect(
      mod.useMessageQueueStore.getState().getQueue("sess-bc-throws").length,
    ).toBe(1);
  });

  it("degrades to direct execution when navigator itself is absent", async () => {
    vi.stubGlobal("navigator", undefined);

    const mod = await import("./messageQueueStore");
    const out = await mod.withSendLock("sess-no-nav", () => "direct");

    expect(out).toBe("direct");
    expect(typeof navigator).toBe("undefined");
  });
});
