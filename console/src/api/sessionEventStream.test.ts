import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { subscribePlanUpdates } from "./modules/plan";
import { subscribeUserInputUpdates } from "./modules/userInput";
import { subscribeRuntimeStatusUpdates } from "./modules/runtimeStatus";
import { subscribeSessionEvents } from "./sessionEventStream";
const auth = vi.hoisted(() => ({
  generation: 0,
  listeners: new Set<() => void>(),
}));
vi.mock("./authSession", () => ({
  getAccessSessionGeneration: () => auth.generation,
  subscribeAccessSessionGeneration: (listener: () => void) => {
    auth.listeners.add(listener);
    return () => auth.listeners.delete(listener);
  },
}));
vi.mock("./config", () => ({ getApiUrl: (path: string) => path }));
vi.mock("./authHeaders", () => ({ buildAuthHeaders: () => ({}) }));
beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  auth.listeners.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it.each([
  subscribePlanUpdates,
  subscribeUserInputUpdates,
  subscribeRuntimeStatusUpdates,
])(
  "backs off after a successful EOF and stops reconnecting on cleanup",
  async (subscribe) => {
    const fetch = vi
      .fn()
      .mockImplementation(() =>
        fetch.mock.calls.length >= 12
          ? new Promise(() => {})
          : Promise.resolve(new Response("", { status: 200 })),
      );
    vi.stubGlobal("fetch", fetch);
    const stop = subscribe(() => {});
    try {
      for (let i = 0; i < 100; i++) await Promise.resolve();
      expect(fetch).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(3000);
      expect(fetch).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(5999);
      expect(fetch).toHaveBeenCalledTimes(2);
      stop();
      await vi.advanceTimersByTimeAsync(60000);
      expect(fetch).toHaveBeenCalledTimes(2);
    } finally {
      stop();
    }
  },
);

it("decodes split UTF-8, CRLF and multiline frames while ignoring malformed data", async () => {
  const bytes = new TextEncoder().encode(
    ': keepalive\r\ndata: broken\r\n\r\ndata: {"type":"plan_update",\r\ndata: "session_id":"a","plan":{"name":"中文计划"}}\r\n\r\n',
  );
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    },
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream)));
  const receive = vi.fn();
  const stop = subscribePlanUpdates(receive);
  try {
    await vi.advanceTimersByTimeAsync(0);
    expect(receive).toHaveBeenCalledExactlyOnceWith({ name: "中文计划" }, "a");
  } finally {
    stop();
  }
});

it("pauses offline, retries online and retains the captured agent", async () => {
  const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  const fetch = vi.fn().mockResolvedValue(new Response("", { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const stop = subscribePlanUpdates(vi.fn(), undefined, { agentId: "agent-a" });
  try {
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch).not.toHaveBeenCalled();
    online.mockReturnValue(true);
    window.dispatchEvent(new Event("online"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].headers["X-Agent-Id"]).toBe("agent-a");
    online.mockReturnValue(false);
    window.dispatchEvent(new Event("offline"));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch).toHaveBeenCalledTimes(1);
  } finally {
    stop();
  }
});

it("aborts a stalled connection after the opening timeout before retrying", async () => {
  const fetch = vi.fn().mockImplementation(
    (_url, { signal }: { signal: AbortSignal }) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      }),
  );
  vi.stubGlobal("fetch", fetch);
  const stop = subscribePlanUpdates(vi.fn());
  try {
    await vi.advanceTimersByTimeAsync(15_000);
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally {
    stop();
  }
});

it("drops buffered events and cancels reconnects after authentication changes", async () => {
  let streamController!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      streamController = controller;
    },
  });
  const fetch = vi.fn().mockResolvedValue(new Response(stream));
  vi.stubGlobal("fetch", fetch);
  const receive = vi.fn();
  const stop = subscribeSessionEvents("/test", receive);
  try {
    await vi.advanceTimersByTimeAsync(0);
    auth.generation += 1;
    auth.listeners.forEach((listener) => listener());
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    streamController.enqueue(
      new TextEncoder().encode('data: {"type":"late"}\n\n'),
    );
    streamController.close();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(receive).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
  } finally {
    stop();
  }
});

it("shares a transport and releases it only when its last subscriber leaves", async () => {
  let source!: ReadableStreamDefaultController<Uint8Array>;
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      new ReadableStream({
        start(c) {
          source = c;
        },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const one = vi.fn(),
    two = vi.fn();
  const stopOne = subscribeSessionEvents("/shared", one, undefined, {
    agentId: "a",
  });
  const stopTwo = subscribeSessionEvents("/shared", two, undefined, {
    agentId: "a",
  });
  await vi.advanceTimersByTimeAsync(0);
  expect(fetch).toHaveBeenCalledTimes(1);
  stopOne();
  source.enqueue(new TextEncoder().encode('data: {"type":"test"}\n\n'));
  await vi.advanceTimersByTimeAsync(0);
  expect(one).not.toHaveBeenCalled();
  expect(two).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(false);
  stopTwo();
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
});

it("closes hidden-tab streams and reopens once when visible", async () => {
  const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const fetch = vi.fn().mockImplementation((_url, { signal }) =>
    Promise.resolve(
      new Response(
        new ReadableStream({
          start(controller) {
            signal.addEventListener("abort", () =>
              controller.error(new DOMException("Aborted", "AbortError")),
            );
          },
        }),
      ),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const stop = subscribeSessionEvents("/visibility", vi.fn());
  try {
    await vi.advanceTimersByTimeAsync(0);
    hidden.mockReturnValue(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally {
    stop();
  }
});

it("replaces a stream whose heartbeat silently stopped", async () => {
  const fetch = vi.fn().mockImplementation((_url, { signal }) =>
    Promise.resolve(
      new Response(
        new ReadableStream({
          start(controller) {
            signal.addEventListener("abort", () =>
              controller.error(new DOMException("Aborted", "AbortError")),
            );
          },
        }),
      ),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const stop = subscribeSessionEvents("/stalled", vi.fn());
  try {
    await vi.advanceTimersByTimeAsync(65_000);
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(3000);
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally {
    stop();
  }
});
