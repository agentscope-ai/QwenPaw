/**
 * Integration guard for the reconnect replay path: the bytes that leave
 * wrapReplayFastForward are fed to the REAL SDK response builder the same
 * way useChatRequest does (responseParser -> builder.handle).
 *
 * The unit tests for the wrapper only assert chunk framing. They cannot
 * catch a marker leaking into the SDK, which is fatal: Builder.handle
 * dereferences `data.object` and routes anything unknown to handleError,
 * appending an ERROR message and flipping the response to Failed — the
 * live tokens that follow the replay are then never rendered.
 */
import { describe, it, expect } from "vitest";
// The vitest config aliases the whole `@agentscope-ai/chat` package to a
// stub (the real 2.3MB bundle OOMs the runner), so reach the compiled
// builder through a relative path — the alias only matches the bare
// package specifier. This keeps the assertion against real SDK code.
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore — compiled JS without bundled types on this deep path
import AgentScopeRuntimeResponseBuilder from "../../../../node_modules/@agentscope-ai/chat/lib/AgentScopeRuntimeWebUI/core/AgentScopeRuntime/Response/Builder.js";
import { wrapReplayFastForward } from "../replayFastForward";
import realReconnectStream from "./fixtures/reconnectReplayStream.txt?raw";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

const MARKER = 'data: {"type": "replay_end"}\n\n';

/** Shape of the builder's accumulated response, as far as we assert. */
interface SdkResponse {
  status: string;
  output?: Array<{ type?: string }>;
}

/** Seed the builder the way useChatRequest does for a fresh turn. */
const builderSeed = {
  id: "r1",
  status: "created",
  created_at: 0,
} as unknown as ConstructorParameters<
  typeof AgentScopeRuntimeResponseBuilder
>[0];

/** Minimal SSE frames of a replayed-then-live assistant turn. */
const replayedFrames = [
  `data: ${JSON.stringify({
    object: "message",
    id: "m1",
    type: "message",
    role: "assistant",
    status: "in_progress",
    content: [{ type: "text", text: "replayed ", index: 0, delta: true }],
  })}\n\n`,
  `data: ${JSON.stringify({
    object: "content",
    msg_id: "m1",
    index: 0,
    type: "text",
    delta: true,
    status: "in_progress",
    text: "part",
  })}\n\n`,
];

const liveFrames = [
  `data: ${JSON.stringify({
    object: "content",
    msg_id: "m1",
    index: 0,
    type: "text",
    delta: true,
    status: "in_progress",
    text: " + live",
  })}\n\n`,
  `data: ${JSON.stringify({
    object: "response",
    id: "r1",
    status: "completed",
    output: [],
  })}\n\n`,
];

function sseResponse(frames: string[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      for (const f of frames) c.enqueue(encoder.encode(f));
      c.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/** Split raw bytes into `data:` payloads, mirroring the SDK's SSE reader. */
async function readSsePayloads(response: Response): Promise<string[]> {
  const reader = response.body!.getReader();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
  }
  return buf
    .split("\n\n")
    .map((e) => e.trim())
    .filter(Boolean)
    .map((e) => e.replace(/^data:\s*/, ""));
}

describe("replay fast-forward -> real SDK response builder", () => {
  it("consumes replayed and live events without a builder error", async () => {
    const wrapped = wrapReplayFastForward(
      sseResponse([...replayedFrames, MARKER, ...liveFrames]),
      5000,
    );
    const payloads = await readSsePayloads(wrapped);

    // No marker survives to the parser stage.
    expect(payloads.some((p) => p.includes("replay_end"))).toBe(false);

    const builder = new AgentScopeRuntimeResponseBuilder(builderSeed);
    let result: SdkResponse | undefined;
    for (const payload of payloads) {
      result = builder.handle(JSON.parse(payload));
    }

    // The live tail was consumed: completed status, no ERROR output.
    expect(result?.status).toBe("completed");
    const errors = (result?.output ?? []).filter((m) => m.type === "error");
    expect(errors).toEqual([]);
  });

  it("consumes a real captured reconnect stream without a builder error", async () => {
    // Fixture captured from a live `POST /console/chat` reconnect against a
    // running generation, so the marker's exact wire format is pinned by
    // real backend output rather than a hand-written guess.
    const wrapped = wrapReplayFastForward(
      sseResponse([realReconnectStream]),
      5000,
    );
    const payloads = await readSsePayloads(wrapped);

    expect(payloads.length).toBeGreaterThan(3);
    expect(payloads.some((p) => p.includes("replay_end"))).toBe(false);

    const builder = new AgentScopeRuntimeResponseBuilder(builderSeed);
    let result: SdkResponse | undefined;
    for (const payload of payloads) {
      result = builder.handle(JSON.parse(payload));
    }
    const errors = (result?.output ?? []).filter((m) => m.type === "error");
    expect(errors).toEqual([]);
    expect(result?.status).not.toBe("failed");
  });

  it("a leaked marker WOULD break the builder (pins why stripping matters)", () => {
    const builder = new AgentScopeRuntimeResponseBuilder(builderSeed);
    const result: SdkResponse = builder.handle({
      type: "replay_end",
    } as unknown as Parameters<typeof builder.handle>[0]);
    // Documents the failure mode the wrapper prevents.
    expect(result.status).toBe("failed");
  });
});
