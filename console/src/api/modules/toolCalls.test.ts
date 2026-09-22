import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { request } from "../request";
import {
  extractOutputText,
  subscribeToolCallStream,
  toolCallStreamUrl,
  toolCallsApi,
  type ToolCallOutput,
} from "./toolCalls";

describe("toolCallsApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
    vi.mocked(request).mockResolvedValue({ status: "ok" });
  });

  it("preventOffload posts no_deadline for offload target", async () => {
    await toolCallsApi.preventOffload("sid-1", "tc-1");
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/sid-1/tc-1/extend-deadline",
      {
        method: "POST",
        body: JSON.stringify({ target: "offload", no_deadline: true }),
      },
    );
  });

  it("extendOffload posts target=offload with seconds", async () => {
    await toolCallsApi.extendOffload("sid-1", "tc-1", 30);
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/sid-1/tc-1/extend-deadline",
      {
        method: "POST",
        body: JSON.stringify({ target: "offload", seconds: 30 }),
      },
    );
  });

  it("extendKill posts target=kill with seconds", async () => {
    await toolCallsApi.extendKill("sid-1", "tc-1", 45);
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/sid-1/tc-1/extend-deadline",
      {
        method: "POST",
        body: JSON.stringify({ target: "kill", seconds: 45 }),
      },
    );
  });

  it("getInfo and cancel use session-scoped paths", async () => {
    await toolCallsApi.getInfo("backend-sid", "tc-9");
    expect(request).toHaveBeenCalledWith("/tool-calls/backend-sid/tc-9");

    await toolCallsApi.cancel("backend-sid", "tc-9");
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/backend-sid/tc-9/cancel",
      { method: "POST" },
    );
  });
});

// ---- Stream helpers -----------------------------------------------------

/** Build an SSE Response whose body is exactly `body` (already framed). */
function sseResponse(body: string, status = 200): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status });
}

/** Frame payloads the way the backend does: `data: <json>` separated by \n\n. */
const frame = (...payloads: unknown[]) =>
  payloads.map((p) => `data: ${JSON.stringify(p)}`).join("\n\n") + "\n\n";

const handlers = () => ({
  onChunk: vi.fn(),
  onDone: vi.fn(),
  onError: vi.fn(),
});

describe("toolCallStreamUrl", () => {
  it("builds an api-prefixed stream path for the session and call", () => {
    // getApiUrl is not mocked: VITE_API_BASE_URL is unset under test, so the
    // url is the /api prefix plus the normalised path.
    expect(toolCallStreamUrl("sid-1", "tc-1")).toBe(
      "/api/tool-calls/sid-1/tc-1/stream",
    );
  });
});

describe("extractOutputText", () => {
  const output = (content: ToolCallOutput["content"]): ToolCallOutput => ({
    tool_call_id: "tc-1",
    is_closed: true,
    final_state: "success",
    content,
  });

  it("returns an empty string for an empty content list", () => {
    expect(extractOutputText(output([]))).toBe("");
  });

  it("returns an empty string when content is missing", () => {
    expect(
      extractOutputText({
        tool_call_id: "tc-1",
        is_closed: true,
        final_state: null,
      } as unknown as ToolCallOutput),
    ).toBe("");
  });

  it("joins text blocks with a newline", () => {
    expect(extractOutputText(output([{ text: "a" }, { text: "b" }]))).toBe(
      "a\nb",
    );
  });

  it("serialises a non-text object block", () => {
    expect(extractOutputText(output([{ image_url: "http://x/y.png" }]))).toBe(
      JSON.stringify({ image_url: "http://x/y.png" }),
    );
  });

  it("mixes text and serialised blocks in order", () => {
    expect(
      extractOutputText(output([{ text: "plain" }, { kind: "other" }])),
    ).toBe(`plain\n${JSON.stringify({ kind: "other" })}`);
  });

  it("skips a block whose text is not a string", () => {
    // typeof block.text === "string" fails, so the block falls through to the
    // serialisation branch rather than being pushed as text.
    expect(extractOutputText(output([{ text: 42 }]))).toBe(
      JSON.stringify({ text: 42 }),
    );
  });

  // NOTE: a null block is deliberately NOT asserted here. The current
  // implementation reads `block.text` before its `block !== null` guard, so a
  // null entry throws instead of being skipped; that guard is unreachable.
  // Reported separately as a defect candidate rather than pinned in this
  // coverage PR, which must stay free of product-behaviour claims.

  it("survives a block that cannot be serialised", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    // JSON.stringify throws on a cycle; the catch branch must swallow it.
    expect(extractOutputText(output([circular]))).toBe("");
  });
});

describe("subscribeToolCallStream", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the stream url with auth headers and an abort signal", async () => {
    fetchMock.mockResolvedValue(sseResponse(frame({ type: "chunk", n: 1 })));
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onChunk).toHaveBeenCalled());

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/tool-calls/sid-1/tc-1/stream");
    expect(init.headers).toBeDefined();
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("delivers each data payload to onChunk", async () => {
    fetchMock.mockResolvedValue(
      sseResponse(frame({ type: "chunk", n: 1 }, { type: "chunk", n: 2 })),
    );
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onChunk).toHaveBeenCalledTimes(2);
    expect(h.onChunk).toHaveBeenNthCalledWith(1, { type: "chunk", n: 1 });
    expect(h.onChunk).toHaveBeenNthCalledWith(2, { type: "chunk", n: 2 });
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("calls onDone when the stream ends without a done event", async () => {
    fetchMock.mockResolvedValue(sseResponse(frame({ type: "chunk" })));
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onDone).toHaveBeenCalledTimes(1);
  });

  it("stops at a done event and ignores anything after it", async () => {
    fetchMock.mockResolvedValue(
      sseResponse(
        frame(
          { type: "chunk", n: 1 },
          { type: "done" },
          { type: "chunk", n: 2 },
        ),
      ),
    );
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onDone).toHaveBeenCalledTimes(1);
    expect(h.onChunk).toHaveBeenCalledTimes(1);
    expect(h.onChunk).toHaveBeenCalledWith({ type: "chunk", n: 1 });
  });

  it("ignores an event without a data line", async () => {
    fetchMock.mockResolvedValue(
      sseResponse(`event: ping\n\n${frame({ type: "chunk" })}`),
    );
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onChunk).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("ignores a malformed json payload but keeps reading", async () => {
    fetchMock.mockResolvedValue(
      sseResponse(`data: {not json\n\n${frame({ type: "chunk", ok: true })}`),
    );
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onChunk).toHaveBeenCalledTimes(1);
    expect(h.onChunk).toHaveBeenCalledWith({ type: "chunk", ok: true });
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("parses only the first data line of a multi-line frame", async () => {
    // One SSE frame carrying two data lines (separated by a single \n, the
    // frame itself terminated by \n\n). The reader uses .find(), so only the
    // first data line is parsed. This pins that current behaviour and is what
    // distinguishes the \n\n frame split from a plain \n split (mutation-tested).
    fetchMock.mockResolvedValue(
      sseResponse(
        'data: {"type":"chunk","first":1}\ndata: {"type":"chunk","second":2}\n\n',
      ),
    );
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onChunk).toHaveBeenCalledTimes(1);
    expect(h.onChunk).toHaveBeenCalledWith({ type: "chunk", first: 1 });
  });

  it("reassembles a payload split across two network chunks", async () => {
    const encoder = new TextEncoder();
    const full = frame({ type: "chunk", big: "value" });
    const cut = Math.floor(full.length / 2);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(full.slice(0, cut)));
        controller.enqueue(encoder.encode(full.slice(cut)));
        controller.close();
      },
    });
    fetchMock.mockResolvedValue(new Response(stream, { status: 200 }));
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onDone).toHaveBeenCalled());

    expect(h.onChunk).toHaveBeenCalledTimes(1);
    expect(h.onChunk).toHaveBeenCalledWith({ type: "chunk", big: "value" });
  });

  it("reports a non-ok response through onError and reads no body", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 502 }));
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onError).toHaveBeenCalled());

    expect(h.onError).toHaveBeenCalledTimes(1);
    expect((h.onError.mock.calls[0][0] as Error).message).toBe(
      "stream HTTP 502",
    );
    expect(h.onDone).not.toHaveBeenCalled();
    expect(h.onChunk).not.toHaveBeenCalled();
  });

  it("reports a missing body through onError", async () => {
    // ok: true but body null: an undici-shaped response with no stream.
    fetchMock.mockResolvedValue({
      ok: true,
      body: null,
    } as unknown as Response);
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onError).toHaveBeenCalled());

    expect((h.onError.mock.calls[0][0] as Error).message).toBe(
      "stream has no body",
    );
  });

  it("reports a fetch rejection through onError", async () => {
    const failure = new Error("connection reset");
    fetchMock.mockRejectedValue(failure);
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);
    await vi.waitFor(() => expect(h.onError).toHaveBeenCalled());

    expect(h.onError).toHaveBeenCalledWith(failure);
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("does not report an abort as an error", async () => {
    const abortError = Object.assign(new Error("aborted"), {
      name: "AbortError",
    });
    fetchMock.mockRejectedValue(abortError);
    const h = handlers();

    subscribeToolCallStream("sid-1", "tc-1", h);

    // No component is rendered here, so plain microtask drains are enough:
    // let the rejected fetch settle and then confirm nothing was reported.
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(h.onError).not.toHaveBeenCalled();
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("returns an abort function that aborts the controller", async () => {
    fetchMock.mockResolvedValue(sseResponse(frame({ type: "chunk" })));
    const h = handlers();

    const abort = subscribeToolCallStream("sid-1", "tc-1", h);
    expect(typeof abort).toBe("function");

    abort();
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal!.aborted).toBe(
      true,
    );
  });
});

describe("offload policy endpoints", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
    vi.mocked(request).mockResolvedValue({ default_action: "offload" });
  });

  it("reads the offload policy from the settings path", async () => {
    await toolCallsApi.getOffloadPolicy();
    expect(request).toHaveBeenCalledWith("/settings/offload-policy");
  });

  it("writes the offload policy with a PUT and the chosen action", async () => {
    await toolCallsApi.setOffloadPolicy("keep_foreground");
    expect(request).toHaveBeenCalledWith("/settings/offload-policy", {
      method: "PUT",
      body: JSON.stringify({ default_action: "keep_foreground" }),
    });
  });

  it("lists, reads output, and offloads through session-scoped paths", async () => {
    await toolCallsApi.list("sid-2");
    expect(request).toHaveBeenCalledWith("/tool-calls/sid-2");

    await toolCallsApi.getOutput("sid-2", "tc-3");
    expect(request).toHaveBeenCalledWith("/tool-calls/sid-2/tc-3/output");

    await toolCallsApi.offload("sid-2", "tc-3");
    expect(request).toHaveBeenCalledWith("/tool-calls/sid-2/tc-3/offload", {
      method: "POST",
    });
  });

  it("defaults the extension windows to thirty seconds", async () => {
    await toolCallsApi.extendOffload("sid-3", "tc-4");
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/sid-3/tc-4/extend-deadline",
      {
        method: "POST",
        body: JSON.stringify({ target: "offload", seconds: 30 }),
      },
    );

    await toolCallsApi.extendKill("sid-3", "tc-4");
    expect(request).toHaveBeenCalledWith(
      "/tool-calls/sid-3/tc-4/extend-deadline",
      {
        method: "POST",
        body: JSON.stringify({ target: "kill", seconds: 30 }),
      },
    );
  });
});
