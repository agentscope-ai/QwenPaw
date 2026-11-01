import { afterEach, describe, expect, it, vi } from "vitest";
import {
  capabilities,
  forApp,
  getHost,
  tasks,
  type PawRequestOptions,
} from "../../../src/qwenpaw/plugins/frontend/index.js";

const original = Object.getOwnPropertyDescriptor(window, "QwenPaw");
afterEach(() => {
  if (original) Object.defineProperty(window, "QwenPaw", original);
  else Reflect.deleteProperty(window, "QwenPaw");
});

function hostWith(declaration: unknown) {
  const api = {
    get: vi.fn(async (path: string, _options?: PawRequestOptions) =>
      path === "/.sdk" ? declaration : { run_id: "run" },
    ),
    post: vi.fn(
      async (_path: string, _body: unknown, _options?: PawRequestOptions) => ({
        run_id: "run",
      }),
    ),
  };
  const factory = vi.fn(() => ({ api }));
  const host = { paw: { forApp: factory } };
  Object.defineProperty(window, "QwenPaw", { configurable: true, value: host });
  return { api, factory, host };
}

const supported = {
  sdk_version: "1.0.0",
  app_id: "author-app",
  capabilities: ["tasks"],
};

describe("published plugin SDK runtime", () => {
  it("requires an actual host and binds the requested app", () => {
    Reflect.deleteProperty(window, "QwenPaw");
    expect(() => getHost()).toThrow(/unavailable/);
    const { host, factory } = hostWith(supported);
    expect(getHost()).toBe(host);
    forApp("author-app");
    expect(factory).toHaveBeenCalledWith("author-app");
  });

  it.each([
    undefined,
    { sdk_version: "2.0.0", capabilities: ["tasks"] },
    { sdk_version: "1.0.0", capabilities: [] },
  ])(
    "rejects tasks without a compatible backend capability: %j",
    async (declaration) => {
      const { api } = hostWith(declaration);
      await expect(
        tasks("author-app").start({ message: "hello" }),
      ).rejects.toThrow(/capability/);
      expect(api.post).not.toHaveBeenCalled();
    },
  );

  it("reports an unreachable capability endpoint as unknown", async () => {
    const { api } = hostWith(supported);
    api.get.mockRejectedValue(new Error("offline"));
    expect((await capabilities("author-app")).status).toBe("unknown");
    await expect(
      tasks("author-app").start({ message: "hello" }),
    ).rejects.toThrow(/capability/);
    expect(api.post).not.toHaveBeenCalled();
  });

  it("preserves workspace/session scope and AbortSignal through preflight and task calls", async () => {
    const { api } = hostWith(supported);
    const options = {
      signal: new AbortController().signal,
      query: { agent_id: "one", session_id: "session" },
    };
    const client = tasks("author-app");
    expect((await capabilities("author-app")).status).toBe("supported");
    api.get.mockClear();
    await client.start({ message: "hello", session_id: "session" }, options);
    await client.get("run/other", options);
    await client.cancel("run/other", options);
    expect(api.get.mock.calls).toEqual([
      ["/.sdk", options],
      ["/.sdk", options],
      ["/tasks/run%2Fother", options],
      ["/.sdk", options],
    ]);
    expect(api.post.mock.calls).toEqual([
      ["/tasks", { message: "hello", session_id: "session" }, options],
      ["/tasks/run%2Fother/cancel", {}, options],
    ]);
  });

  it("releases a status subscription without cancelling the underlying task", async () => {
    const { api } = hostWith(supported);
    let closed = false;
    const events = vi.fn(async function* (_path: string, _options: unknown) {
      try {
        yield { data: JSON.stringify({ run_id: "run", status: "running" }) };
        yield { data: JSON.stringify({ run_id: "run", status: "completed" }) };
      } finally {
        closed = true;
      }
    });
    Object.assign(api, { events });
    const options = {
      signal: new AbortController().signal,
      query: { agent_id: "one" },
    };
    const stream = tasks("author-app").stream("run/other", options);
    expect((await stream.next()).value).toEqual({
      run_id: "run",
      status: "running",
    });
    await stream.return(undefined);
    expect(closed).toBe(true);
    expect(api.get).toHaveBeenCalledWith("/.sdk", options);
    expect(events).toHaveBeenCalledWith("/tasks/run%2Fother/stream", {
      ...options,
      method: "GET",
    });
    expect(api.post).not.toHaveBeenCalled();
  });
});
