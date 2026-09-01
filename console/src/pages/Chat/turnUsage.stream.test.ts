/**
 * Retry scheduling and SSE stream observation for turn usage. The trailing
 * `turn_usage` SSE event arrives after the Completed response and may be
 * dropped by the chat SDK, so the stream wrapper captures it and retries
 * patching the final card until the turn ends or attempts are exhausted.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  schedulePatchLastResponseCardUsage,
  wrapChatResponseUsageStream,
} from "./turnUsage";
import { useTurnUsageStore } from "./turnUsageStore";

const usage = { total_tokens: 42 };
const ctx = {
  estimated_tokens: 500,
  max_input_length: 1000,
  context_usage_ratio: 50,
};
const snapshot = { usage, context_usage: ctx };

function makeRef(messages: unknown[]) {
  const updateMessage = vi.fn();
  return {
    // Mock ref shape; cast to the SDK ref type expected by the API.
    ref: {
      current: { messages: { getMessages: () => messages, updateMessage } },
    } as never,
    updateMessage,
  };
}

const assistantCard = (data: Record<string, unknown>) => ({
  role: "assistant" as const,
  cards: [{ code: "AgentScopeRuntimeResponseCard", data }],
});

describe("schedulePatchLastResponseCardUsage", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useTurnUsageStore.getState().invalidateTurn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("skips entirely when the turn is already inactive", () => {
    const { ref, updateMessage } = makeRef([assistantCard({})]);
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    useTurnUsageStore.getState().invalidateTurn();
    schedulePatchLastResponseCardUsage(ref, snapshot, turn);
    vi.runAllTimers();
    expect(updateMessage).not.toHaveBeenCalled();
  });

  it("patches synchronously when the card is ready", () => {
    const { ref, updateMessage } = makeRef([assistantCard({})]);
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    schedulePatchLastResponseCardUsage(ref, snapshot, turn);
    expect(updateMessage).toHaveBeenCalledTimes(1);
  });

  it("retries until the card appears", () => {
    const messages: unknown[] = [];
    const { ref, updateMessage } = makeRef(messages);
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    schedulePatchLastResponseCardUsage(ref, snapshot, turn);
    expect(updateMessage).not.toHaveBeenCalled();
    messages.push(assistantCard({}));
    vi.advanceTimersByTime(60); // first retry at 0ms, then 50ms steps
    expect(updateMessage).toHaveBeenCalledTimes(1);
  });

  it("stops retrying when the turn is invalidated mid-flight", () => {
    const { ref, updateMessage } = makeRef([]);
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    schedulePatchLastResponseCardUsage(ref, snapshot, turn);
    useTurnUsageStore.getState().invalidateTurn();
    vi.runAllTimers();
    expect(updateMessage).not.toHaveBeenCalled();
  });

  it("gives up after the attempt cap", () => {
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    const { ref } = makeRef([]);
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    schedulePatchLastResponseCardUsage(ref, snapshot, turn);
    vi.runAllTimers();
    // initial schedule + 40 retries; never patched
    expect(setTimeoutSpy.mock.calls.length).toBeLessThanOrEqual(42);
    setTimeoutSpy.mockRestore();
  });

  it("works without a turn token (always active)", () => {
    const { ref, updateMessage } = makeRef([assistantCard({})]);
    schedulePatchLastResponseCardUsage(ref, snapshot);
    expect(updateMessage).toHaveBeenCalledTimes(1);
  });
});

function sseResponse(body: string, status = 200): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status });
}

describe("wrapChatResponseUsageStream", () => {
  beforeEach(() => {
    useTurnUsageStore.getState().invalidateTurn();
  });

  it("returns the original response when there is no body", () => {
    const bare = new Response(null);
    const chatRef = { current: null };
    expect(wrapChatResponseUsageStream(bare, chatRef)).toBe(bare);
  });

  it("captures turn_usage SSE payloads and stores the snapshot", async () => {
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    const { ref } = makeRef([assistantCard({})]);
    const body =
      'data: {"type": "message", "text": "hi"}\n\n' +
      `data: ${JSON.stringify({
        type: "turn_usage",
        usage,
        context_usage: ctx,
      })}\n\n`;
    const wrapped = wrapChatResponseUsageStream(sseResponse(body), ref, turn);
    await wrapped.text(); // drain the stream to trigger flush
    expect(useTurnUsageStore.getState().snapshot).toEqual(snapshot);
  });

  it("keeps the last turn_usage payload when several arrive", async () => {
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    const { ref } = makeRef([assistantCard({})]);
    const first = { type: "turn_usage", usage: { total_tokens: 1 } };
    const second = { type: "turn_usage", usage: { total_tokens: 2 } };
    const body =
      `data: ${JSON.stringify(first)}\n\n` +
      `data: ${JSON.stringify(second)}\n\n`;
    const wrapped = wrapChatResponseUsageStream(sseResponse(body), ref, turn);
    await wrapped.text();
    expect(useTurnUsageStore.getState().snapshot?.usage?.total_tokens).toBe(2);
  });

  it("ignores SSE events that are not turn_usage", async () => {
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    const { ref } = makeRef([]);
    const body = 'data: {"type": "message"}\n\n';
    const wrapped = wrapChatResponseUsageStream(sseResponse(body), ref, turn);
    await wrapped.text();
    expect(useTurnUsageStore.getState().snapshot).toBeNull();
  });

  it("handles payloads split across chunk boundaries", async () => {
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    const { ref } = makeRef([assistantCard({})]);
    const payload = JSON.stringify({
      type: "turn_usage",
      usage,
      context_usage: ctx,
    });
    const full = `data: ${payload}\n\n`;
    const half = Math.floor(full.length / 2);
    const enc = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(enc.encode(full.slice(0, half)));
        controller.enqueue(enc.encode(full.slice(half)));
        controller.close();
      },
    });
    const wrapped = wrapChatResponseUsageStream(
      new Response(stream, { status: 200 }),
      ref,
      turn,
    );
    await wrapped.text();
    expect(useTurnUsageStore.getState().snapshot).toEqual(snapshot);
  });

  it("rejects stale-turn snapshots but still passes through", async () => {
    const stale = useTurnUsageStore.getState().beginTurn("a", "s");
    useTurnUsageStore.getState().beginTurn("a", "s"); // new turn supersedes
    const { ref } = makeRef([assistantCard({})]);
    const body = `data: ${JSON.stringify({ type: "turn_usage", usage })}\n\n`;
    const wrapped = wrapChatResponseUsageStream(sseResponse(body), ref, stale);
    await wrapped.text();
    expect(useTurnUsageStore.getState().snapshot).toBeNull();
  });

  it("stores via setSnapshot when no turn token is given", async () => {
    const { ref } = makeRef([assistantCard({})]);
    const body = `data: ${JSON.stringify({ type: "turn_usage", usage })}\n\n`;
    const wrapped = wrapChatResponseUsageStream(sseResponse(body), ref);
    await wrapped.text();
    expect(useTurnUsageStore.getState().snapshot?.usage).toEqual(usage);
  });

  it("tolerates malformed JSON data lines", async () => {
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    const { ref } = makeRef([]);
    const body =
      "data: {broken json with turn_usage keyword\n\n" +
      `data: ${JSON.stringify({ type: "turn_usage", usage })}\n\n`;
    const wrapped = wrapChatResponseUsageStream(sseResponse(body), ref, turn);
    await wrapped.text();
    expect(useTurnUsageStore.getState().snapshot?.usage).toEqual(usage);
  });

  it("preserves status and headers of the original response", () => {
    const turn = useTurnUsageStore.getState().beginTurn("a", "s");
    const { ref } = makeRef([]);
    const original = sseResponse("data: {}\n\n", 201);
    original.headers.set("x-test", "1");
    const wrapped = wrapChatResponseUsageStream(original, ref, turn);
    expect(wrapped.status).toBe(201);
    expect(wrapped.headers.get("x-test")).toBe("1");
  });
});
