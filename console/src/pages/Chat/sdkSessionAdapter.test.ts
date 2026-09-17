import { describe, expect, it, vi } from "vitest";
import type { IAgentScopeRuntimeWebUISessionAPI } from "@agentscope-ai/chat";
import { createSdkSessionAdapter } from "./sdkSessionAdapter";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const session = (id: string) => ({ id, name: id, messages: [] });
function source(
  getSession = vi.fn<IAgentScopeRuntimeWebUISessionAPI["getSession"]>(),
) {
  return {
    getSession,
    getSessionList: vi.fn(async () => []),
    updateSession: vi.fn(async () => []),
    removeSession: vi.fn(async () => []),
    createSession: vi.fn(async () => ({
      sessions: [session("created")],
      session: session("created"),
    })),
  };
}

describe("SDK session hydration boundary", () => {
  it("keeps submission blocked until the existing SDK history request settles", async () => {
    const history = deferred<ReturnType<typeof session>>();
    const api = source(vi.fn(() => history.promise));
    const adapter = createSdkSessionAdapter(api);
    expect(adapter.isReady("chat-a")).toBe(false);
    const load = adapter.api.getSession("chat-a");
    expect(adapter.isReady("chat-a")).toBe(false);
    history.resolve(session("chat-a"));
    await load;
    expect(adapter.isReady("chat-a")).toBe(true);
    expect(api.getSession).toHaveBeenCalledTimes(1);
  });
  it("marks the Chat UUID ready when history loads through a runtime alias", async () => {
    const api = source(
      vi.fn(async () => ({
        ...session("runtime-uuid"),
        realId: "chat-uuid",
      })),
    );
    const adapter = createSdkSessionAdapter(api);

    await adapter.api.getSession("runtime-uuid");

    expect(adapter.isReady("runtime-uuid")).toBe(true);
    expect(adapter.isReady("chat-uuid")).toBe(true);
  });
  it("does not let an older history load release a newer reload", async () => {
    const old = deferred<ReturnType<typeof session>>(),
      fresh = deferred<ReturnType<typeof session>>();
    const adapter = createSdkSessionAdapter(
      source(
        vi
          .fn()
          .mockReturnValueOnce(old.promise)
          .mockReturnValueOnce(fresh.promise),
      ),
    );
    const p1 = adapter.api.getSession("a"),
      p2 = adapter.api.getSession("a");
    old.resolve(session("a"));
    await p1;
    expect(adapter.isReady("a")).toBe(false);
    fresh.resolve(session("a"));
    await p2;
    expect(adapter.isReady("a")).toBe(true);
  });
  it("keeps failed loads blocked, supports retry, and isolates Agent epochs", async () => {
    const api = source(
      vi
        .fn()
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValue(session("a")),
    );
    const a = createSdkSessionAdapter(api),
      b = createSdkSessionAdapter(source());
    await expect(a.api.getSession("a")).rejects.toThrow("offline");
    expect(a.isReady("a")).toBe(false);
    await a.api.getSession("a");
    expect(a.isReady("a")).toBe(true);
    expect(b.isReady("a")).toBe(false);
  });
  it("accepts an SDK-created empty session without a second history load, then invalidates deletion", async () => {
    const adapter = createSdkSessionAdapter(source());
    expect(adapter.isReady()).toBe(true);
    await adapter.api.createSession({});
    expect(adapter.isReady("created")).toBe(true);
    await adapter.api.removeSession({ id: "created" });
    expect(adapter.isReady("created")).toBe(false);
  });
});
