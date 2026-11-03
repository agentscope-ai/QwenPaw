import { afterEach, describe, expect, it, vi } from "vitest";
import Builder from "@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder";
import { batchLiveChatDeltas } from "./liveDeltaBatch";

const delta = (text: string, msg_id = "m1") => ({
  object: "content",
  type: "text",
  delta: true,
  msg_id,
  text,
});
function fixture(signal?: AbortSignal) {
  let source!: ReadableStreamDefaultController<Uint8Array>;
  const cancel = vi.fn();
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        source = controller;
      },
      cancel,
    }),
  );
  const reader = batchLiveChatDeltas(response, signal).body!.getReader();
  const raw = (text: string) => source.enqueue(new TextEncoder().encode(text));
  const emit = (...events: object[]) =>
    raw(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""));
  const read = async () => {
    const { value } = await reader.read();
    return JSON.parse(new TextDecoder().decode(value).slice(5).trim());
  };
  return { source, reader, emit, read, raw, cancel };
}

describe("live delta batching", () => {
  afterEach(() => vi.useRealTimers());

  it("combines changed text without response snapshots", async () => {
    vi.useFakeTimers();
    const stream = fixture();
    const next = stream.read();
    stream.emit(...Array.from({ length: 100 }, () => delta("中")));
    await vi.advanceTimersByTimeAsync(50);
    expect(await next).toEqual(delta("中".repeat(100)));
    await stream.reader.cancel();
  });

  it("preserves SDK state across tool, usage and terminal boundaries", async () => {
    const initial = {
      object: "response",
      id: "r1",
      status: "in_progress",
      output: [],
    };
    const events = [
      initial,
      {
        object: "message",
        id: "m1",
        type: "message",
        role: "assistant",
        content: [],
      },
      delta("first"),
      delta(" second"),
      { object: "message", id: "tool", type: "plugin_call", content: [] },
      {
        object: "content",
        msg_id: "tool",
        type: "data",
        delta: true,
        data: { input: "pwd" },
      },
      delta(" third"),
      { type: "turn_usage", usage: { total_tokens: 12 } },
      { ...initial, status: "completed" },
    ];
    const stream = fixture();
    stream.emit(...events);
    stream.source.close();
    const received = [];
    for (;;) {
      const { done, value } = await stream.reader.read();
      if (done) break;
      received.push(JSON.parse(new TextDecoder().decode(value).slice(5)));
    }
    const materialize = (items: object[]) => {
      const builder = new Builder(initial as never);
      for (const item of items) {
        if (!("type" in item && item.type === "turn_usage"))
          builder.handle(item as never);
      }
      return builder.data;
    };
    expect(materialize(received)).toEqual(materialize(events));
    expect(received).toHaveLength(events.length - 1);
    expect(received[received.length - 1].status).toBe("completed");
  });

  it("keeps distinct blocks and message ids separate", async () => {
    const stream = fixture();
    const events = [
      delta("a"),
      delta("b", "m2"),
      { ...delta("c"), index: 1 },
      { ...delta("d"), index: 2 },
    ];
    stream.emit(...events);
    stream.source.close();
    for (const event of events) expect(await stream.read()).toEqual(event);
    expect((await stream.reader.read()).done).toBe(true);
  });

  it("bounds UTF-8 bytes and flushes on EOF", async () => {
    const stream = fixture();
    const text = "中".repeat(12000);
    stream.emit(delta(text), delta(text));
    stream.source.close();
    expect(await stream.read()).toEqual(delta(text));
    expect(await stream.read()).toEqual(delta(text));
  });

  it("handles split CRLF and preserves named SSE frames", async () => {
    const stream = fixture();
    stream.raw(`data: ${JSON.stringify(delta("a"))}\r\n\r`);
    stream.raw("\nevent: checkpoint\r\nid: 42\r\ndata: {}\r\n\r\n");
    expect(await stream.read()).toEqual(delta("a"));
    const result = await stream.reader.read();
    expect(new TextDecoder().decode(result.value)).toBe(
      "event: checkpoint\nid: 42\ndata: {}\n\n",
    );
    await stream.reader.cancel();
  });

  it.each([false, true])(
    "preserves received frames on abort with backpressure=%s",
    async (backpressure) => {
      vi.useFakeTimers();
      const abort = new AbortController();
      const stream = fixture(abort.signal);
      if (backpressure)
        stream.emit({ object: "response", output: [] }, delta("received"));
      else stream.emit(delta("received"));
      await vi.advanceTimersByTimeAsync(10);
      abort.abort();
      if (backpressure)
        expect(await stream.read()).toEqual({ object: "response", output: [] });
      expect(await stream.read()).toEqual(delta("received"));
      await expect(stream.reader.read()).rejects.toMatchObject({
        name: "AbortError",
      });
      await vi.advanceTimersByTimeAsync(100);
      expect(stream.cancel).toHaveBeenCalledOnce();
    },
  );

  it("propagates upstream errors", async () => {
    const stream = fixture();
    stream.emit(delta("received"));
    stream.source.error(new Error("transport failed"));
    await expect(stream.reader.read()).rejects.toThrow("transport failed");
  });
});
