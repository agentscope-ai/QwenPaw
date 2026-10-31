// Contract tests for the PawApp dependencies SDK namespace.
//
// Scope note: this file covers createDependenciesNamespace() end to end, which
// the sibling pawapp-sdk tests leave untouched (browserSession.test.ts covers
// the browser-session bootstrap, context.test.ts covers app-id resolution).
// Everything asserted here is the request contract: path, verb, body and the
// polling/dispose lifecycle of subscribe(). No backend behaviour is asserted.
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";
import { createDependenciesNamespace } from "./dependencies";
import type {
  PawApiNamespace,
  PawDependencySnapshot,
  PawDependencyStatus,
} from "./types";

const LIST_PATH = "/dependencies";

function snapshot(id: string): PawDependencySnapshot {
  return {
    schema_version: "1",
    app_id: "office",
    summary: "healthy",
    dependencies: [status(id)],
    capabilities: [],
  };
}

function status(id: string): PawDependencyStatus {
  return {
    id,
    display_name: id,
    ownership: "host_managed",
    required: true,
    lifecycle: "running",
    health: "healthy",
    error_code: null,
    message: "",
    remediation: null,
    capabilities: ["check"],
    actions: ["check", "restart"],
    last_checked_at: "2026-09-21T00:00:00Z",
    latency_ms: 12,
  };
}

/** Minimal PawApiNamespace stub: only get/post are used by this namespace. */
function makeApi() {
  const get = vi.fn() as Mock;
  const post = vi.fn() as Mock;
  const api = { get, post } as unknown as PawApiNamespace;
  return { api, get, post };
}

/** Let every pending microtask drain (used after awaiting a resolved stub). */
async function flush(times = 4) {
  for (let i = 0; i < times; i += 1) {
    await Promise.resolve();
  }
}

describe("createDependenciesNamespace - list()", () => {
  let api: ReturnType<typeof makeApi>;

  beforeEach(() => {
    api = makeApi();
  });

  it("requests the snapshot collection without a query by default", async () => {
    const expected = snapshot("dep-a");
    api.get.mockResolvedValue(expected);
    const deps = createDependenciesNamespace(api.api);

    await expect(deps.list()).resolves.toBe(expected);
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith(LIST_PATH, {
      query: undefined,
    });
  });

  it("omits the force query when called with an explicit false", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);

    await deps.list(false);
    expect(api.get).toHaveBeenCalledWith(LIST_PATH, {
      query: undefined,
    });
  });

  it("sends force=true as a query flag when forced", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);

    await deps.list(true);
    expect(api.get).toHaveBeenCalledWith(LIST_PATH, {
      query: { force: true },
    });
  });
});

describe("createDependenciesNamespace - get()", () => {
  let api: ReturnType<typeof makeApi>;

  beforeEach(() => {
    api = makeApi();
  });

  it("targets the single dependency path", async () => {
    const expected = status("dep-a");
    api.get.mockResolvedValue(expected);
    const deps = createDependenciesNamespace(api.api);

    await expect(deps.get("dep-a")).resolves.toBe(expected);
    expect(api.get).toHaveBeenCalledWith("/dependencies/dep-a", {
      query: undefined,
    });
  });

  it("percent-encodes the dependency id but keeps the route readable", async () => {
    api.get.mockResolvedValue(status("x"));
    const deps = createDependenciesNamespace(api.api);

    await deps.get("我的 dep/a?b");
    const calledWith = api.get.mock.calls[0][0] as string;
    expect(calledWith).toBe(
      `/dependencies/${encodeURIComponent("我的 dep/a?b")}`,
    );
    // The separator between route and id must stay a literal slash.
    expect(calledWith.startsWith("/dependencies/")).toBe(true);
    expect(calledWith).not.toContain("%2Fdependencies");
  });

  it("forwards the force flag only when asked", async () => {
    api.get.mockResolvedValue(status("x"));
    const deps = createDependenciesNamespace(api.api);

    await deps.get("dep-a", true);
    await deps.get("dep-a", false);
    expect(api.get.mock.calls[0][1]).toEqual({ query: { force: true } });
    expect(api.get.mock.calls[1][1]).toEqual({ query: undefined });
  });
});

describe("createDependenciesNamespace - check()", () => {
  let api: ReturnType<typeof makeApi>;

  beforeEach(() => {
    api = makeApi();
  });

  it("posts to the check action without a body", async () => {
    const expected = status("dep-a");
    api.post.mockResolvedValue(expected);
    const deps = createDependenciesNamespace(api.api);

    await expect(deps.check("dep-a")).resolves.toBe(expected);
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post).toHaveBeenCalledWith("/dependencies/dep-a/actions/check");
  });

  it("percent-encodes the id on the check route too", async () => {
    api.post.mockResolvedValue(status("x"));
    const deps = createDependenciesNamespace(api.api);

    await deps.check("a b/c");
    expect(api.post.mock.calls[0][0]).toBe(
      `/dependencies/${encodeURIComponent("a b/c")}/actions/check`,
    );
  });
});

describe("createDependenciesNamespace - action()", () => {
  let api: ReturnType<typeof makeApi>;

  beforeEach(() => {
    api = makeApi();
  });

  it("posts to the named action route with an empty body", async () => {
    const expected = status("dep-a");
    api.post.mockResolvedValue(expected);
    const deps = createDependenciesNamespace(api.api);

    await expect(deps.action("dep-a", "restart")).resolves.toBe(expected);
    expect(api.post).toHaveBeenCalledTimes(1);
    const [path, body, opts] = api.post.mock.calls[0];
    expect(path).toBe("/dependencies/dep-a/actions/restart");
    expect(body).toBeUndefined();
    expect(opts).toBeUndefined();
  });

  it("encodes the dependency id and appends the action segment", async () => {
    api.post.mockResolvedValue(status("x"));
    const deps = createDependenciesNamespace(api.api);

    await deps.action("我的 dep", "provision");
    const path = api.post.mock.calls[0][0] as string;
    expect(path).toBe(
      `/dependencies/${encodeURIComponent("我的 dep")}/actions/provision`,
    );
    // The id must be percent-encoded while the route separators stay literal.
    expect(path).not.toContain("我的");
    expect(path.startsWith("/dependencies/")).toBe(true);
  });

  it("sends the idempotency key as a header when supplied", async () => {
    api.post.mockResolvedValue(status("x"));
    const deps = createDependenciesNamespace(api.api);

    await deps.action("dep-a", "start", { idempotencyKey: "key-1" });
    expect(api.post.mock.calls[0][2]).toEqual({
      headers: { "Idempotency-Key": "key-1" },
    });
  });

  it("omits the options argument when the key is an empty string", async () => {
    api.post.mockResolvedValue(status("x"));
    const deps = createDependenciesNamespace(api.api);

    await deps.action("dep-a", "start", { idempotencyKey: "" });
    expect(api.post.mock.calls[0][2]).toBeUndefined();
  });

  it("omits the options argument when options carry no key", async () => {
    api.post.mockResolvedValue(status("x"));
    const deps = createDependenciesNamespace(api.api);

    await deps.action("dep-a", "stop", {});
    expect(api.post.mock.calls[0][2]).toBeUndefined();
  });
});

describe("createDependenciesNamespace - subscribe()", () => {
  let api: ReturnType<typeof makeApi>;

  beforeEach(() => {
    vi.useFakeTimers();
    api = makeApi();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("polls immediately and then on the default 10s interval", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);
    const listener = vi.fn();

    const handle = deps.subscribe(listener);
    await flush();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(snapshot("dep-a"));
    expect(api.get).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(9_999);
    expect(api.get).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1);
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(listener).toHaveBeenCalledTimes(2);

    handle.dispose();
  });

  it("honours a custom interval", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);
    const listener = vi.fn();

    const handle = deps.subscribe(listener, { intervalMs: 1_500 });
    await flush();
    expect(api.get).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(1_499);
    expect(api.get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(api.get).toHaveBeenCalledTimes(2);

    handle.dispose();
  });

  it("clamps intervals below one second up to 1000ms", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);
    const listener = vi.fn();

    const handle = deps.subscribe(listener, { intervalMs: 10 });
    await flush();
    expect(api.get).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(999);
    expect(api.get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(api.get).toHaveBeenCalledTimes(2);

    handle.dispose();
  });

  it("passes force through to the polled list() call", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);

    const handle = deps.subscribe(vi.fn(), { force: true });
    await flush();
    expect(api.get).toHaveBeenCalledWith(LIST_PATH, {
      query: { force: true },
    });
    handle.dispose();
  });

  it("treats a falsy force option as no query flag", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);

    const handle = deps.subscribe(vi.fn(), { force: false });
    await flush();
    expect(api.get).toHaveBeenCalledWith(LIST_PATH, {
      query: undefined,
    });
    handle.dispose();
  });

  it("swallows a failed poll but keeps the subscription alive", async () => {
    api.get
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);
    const listener = vi.fn();

    const handle = deps.subscribe(listener, { intervalMs: 1_000 });
    await flush();
    expect(listener).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1_000);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledWith(snapshot("dep-a"));

    handle.dispose();
  });

  it("stops calling the listener and stops rescheduling after dispose", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);
    const listener = vi.fn();

    const handle = deps.subscribe(listener, { intervalMs: 1_000 });
    await flush();
    expect(listener).toHaveBeenCalledTimes(1);

    handle.dispose();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(listener).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("does not notify a listener for a snapshot that lands after dispose", async () => {
    // The request is still in flight when dispose() runs, so the resolved
    // snapshot must not reach the listener.
    let release: (value: PawDependencySnapshot) => void = () => {};
    api.get.mockImplementation(
      () =>
        new Promise<PawDependencySnapshot>((resolve) => {
          release = resolve;
        }),
    );
    const deps = createDependenciesNamespace(api.api);
    const listener = vi.fn();

    const handle = deps.subscribe(listener);
    await flush();
    expect(listener).not.toHaveBeenCalled();

    handle.dispose();
    release(snapshot("dep-a"));
    await flush();
    await vi.advanceTimersByTimeAsync(30_000);

    expect(listener).not.toHaveBeenCalled();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("is safe to dispose twice and before the first snapshot resolves", async () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    const deps = createDependenciesNamespace(api.api);

    const handle = deps.subscribe(vi.fn());
    expect(() => {
      handle.dispose();
      handle.dispose();
    }).not.toThrow();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("keeps two subscriptions independent", async () => {
    api.get.mockResolvedValue(snapshot("dep-a"));
    const deps = createDependenciesNamespace(api.api);
    const first = vi.fn();
    const second = vi.fn();

    const a = deps.subscribe(first, { intervalMs: 1_000 });
    const b = deps.subscribe(second, { intervalMs: 2_000 });
    await flush();
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);

    a.dispose();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(2);

    b.dispose();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(second).toHaveBeenCalledTimes(2);
  });
});
