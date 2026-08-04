/**
 * Reconnect fast-forward: the backend replays the buffered SSE events on
 * reconnect and terminates the replayed section with a
 * `{"type": "replay_end"}` marker event. Everything before the marker
 * must reach the SDK as a single chunk (instant render, no token-by-token
 * re-animation); everything after must stream through untouched.
 *
 * The marker itself must NEVER appear in the output: the SDK's response
 * builder dereferences `data.object` on every parsed event, so any
 * non-response payload reaching it throws mid-stream and kills all
 * subsequent live tokens. Stripping happens here, at the byte level.
 *
 * Backends without the marker fall back to an idle-timeout flush.
 */
import { describe, it, expect } from "vitest";
import { wrapReplayFastForward } from "../replayFastForward";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

const MARKER = 'data: {"type": "replay_end"}\n\n';

/** Build an SSE Response whose chunks are pushed via the returned fns. */
function makeSseResponse(): {
  response: Response;
  push: (text: string) => void;
  close: () => void;
} {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  const response = new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
  return {
    response,
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
  };
}

async function readAllChunks(response: Response): Promise<string[]> {
  const reader = response.body!.getReader();
  const chunks: string[] = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(decoder.decode(value));
  }
  return chunks;
}

describe("wrapReplayFastForward", () => {
  it("flushes all replayed events as one chunk and strips the marker", async () => {
    const { response, push, close } = makeSseResponse();
    const wrapped = wrapReplayFastForward(response, 5000);

    push("data: one\n\n");
    push("data: two\n\n");
    push(MARKER);
    push("data: live\n\n");
    close();

    const chunks = await readAllChunks(wrapped);
    expect(chunks[0]).toBe("data: one\n\ndata: two\n\n");
    expect(chunks.slice(1)).toEqual(["data: live\n\n"]);
    // The marker never reaches the SDK parser.
    expect(chunks.join("")).not.toContain("replay_end");
  });

  it("detects and strips a marker split across chunk boundaries", async () => {
    const { response, push, close } = makeSseResponse();
    const wrapped = wrapReplayFastForward(response, 5000);

    push("data: one\n\n");
    push(MARKER.slice(0, 10));
    push(MARKER.slice(10));
    push("data: live\n\n");
    close();

    const chunks = await readAllChunks(wrapped);
    expect(chunks[0]).toBe("data: one\n\n");
    expect(chunks.slice(1)).toEqual(["data: live\n\n"]);
    expect(chunks.join("")).not.toContain("replay_end");
  });

  it("falls back to an idle-timeout flush when no marker is sent", async () => {
    const { response, push, close } = makeSseResponse();
    const wrapped = wrapReplayFastForward(response, 20);

    push("data: one\n\n");
    push("data: two\n\n");

    const reader = wrapped.body!.getReader();
    const first = await reader.read();
    expect(decoder.decode(first.value)).toBe("data: one\n\ndata: two\n\n");

    // After the fallback flush the stream is passthrough.
    push("data: three\n\n");
    const second = await reader.read();
    expect(decoder.decode(second.value)).toBe("data: three\n\n");

    close();
    const end = await reader.read();
    expect(end.done).toBe(true);
  });

  it("strips a marker arriving after the idle-timeout flush", async () => {
    const { response, push, close } = makeSseResponse();
    const wrapped = wrapReplayFastForward(response, 20);

    push("data: one\n\n");

    const reader = wrapped.body!.getReader();
    const first = await reader.read();
    expect(decoder.decode(first.value)).toBe("data: one\n\n");

    // Late replay tail: marker + live event in the same network chunk.
    push(`${MARKER}data: live\n\n`);
    const second = await reader.read();
    expect(decoder.decode(second.value)).toBe("data: live\n\n");

    close();
    const end = await reader.read();
    expect(end.done).toBe(true);
  });

  it("flushes buffered events when the stream ends without a marker", async () => {
    const { response, push, close } = makeSseResponse();
    const wrapped = wrapReplayFastForward(response, 5000);

    push("data: only\n\n");
    close();

    const chunks = await readAllChunks(wrapped);
    expect(chunks).toEqual(["data: only\n\n"]);
  });

  it("forwards a trailing partial event at stream end", async () => {
    const { response, push, close } = makeSseResponse();
    const wrapped = wrapReplayFastForward(response, 5000);

    push("data: one\n\n");
    push(MARKER);
    push("data: partial");
    close();

    const chunks = await readAllChunks(wrapped);
    expect(chunks.join("")).toBe("data: one\n\ndata: partial");
  });

  it("returns the response unchanged when there is no body or not ok", () => {
    const bad = new Response(null, { status: 500 });
    expect(wrapReplayFastForward(bad, 100)).toBe(bad);
  });
});
