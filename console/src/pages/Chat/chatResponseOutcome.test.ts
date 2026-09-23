import { describe, expect, it, vi } from "vitest";

import {
  getChatErrorCode,
  getChatResponseOutcome,
  isModelNotConfiguredError,
  isPreExecutionConfigurationError,
  readErrorPayload,
  wrapChatResponseOutcomeStream,
} from "./chatResponseOutcome";

const encoder = new TextEncoder();

function sseResponse(chunks: string[], init: ResponseInit = {}): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
    ...init,
  });
}

async function drain(response: Response): Promise<string> {
  let text = "";
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  for (;;) {
    const result = await reader.read();
    if (result.done) break;
    text += decoder.decode(result.value, { stream: true });
  }
  return text + decoder.decode();
}

const failedTerminal = JSON.stringify({
  object: "response",
  status: "failed",
  error: { code: "MODEL_NOT_CONFIGURED", message: "No active model" },
});

describe("getChatErrorCode", () => {
  it("reads a flat error object", () => {
    expect(getChatErrorCode({ error: { code: "MODEL_NOT_CONFIGURED" } })).toBe(
      "MODEL_NOT_CONFIGURED",
    );
  });

  it("reads a FastAPI detail object", () => {
    expect(
      getChatErrorCode({
        detail: { code: "AGENT_CONFIG_UNAVAILABLE", message: "unavailable" },
      }),
    ).toBe("AGENT_CONFIG_UNAVAILABLE");
  });

  it("reads a top-level code", () => {
    expect(getChatErrorCode({ code: "CHAT_STREAM_INCOMPLETE" })).toBe(
      "CHAT_STREAM_INCOMPLETE",
    );
  });

  it("returns undefined for a legacy string error", () => {
    expect(getChatErrorCode({ error: "Model not configured" })).toBeUndefined();
    expect(isModelNotConfiguredError({ error: "Model not configured" })).toBe(
      false,
    );
  });

  it("does not match a missing model on transport failures", () => {
    expect(isModelNotConfiguredError({ detail: { code: "EPIPE" } })).toBe(
      false,
    );
    expect(isModelNotConfiguredError(null)).toBe(false);
  });

  it("matches an explicit missing-model verdict", () => {
    expect(
      isModelNotConfiguredError({ detail: { code: "MODEL_NOT_CONFIGURED" } }),
    ).toBe(true);
  });
});

describe("getChatResponseOutcome", () => {
  it("reads a completed terminal", () => {
    expect(
      getChatResponseOutcome({ object: "response", status: "completed" }),
    ).toEqual({ status: "completed", errorCode: undefined, errorMessage: undefined });
  });

  it("reads a failed terminal with its code", () => {
    expect(
      getChatResponseOutcome({
        object: "response",
        status: "failed",
        error: { code: "AGENT_CONFIG_STALE", message: "changed on disk" },
      }),
    ).toEqual({
      status: "failed",
      errorCode: "AGENT_CONFIG_STALE",
      errorMessage: "changed on disk",
    });
  });

  it("ignores non-terminal payloads", () => {
    expect(getChatResponseOutcome({ type: "turn_usage" })).toBeNull();
    expect(getChatResponseOutcome({ object: "message" })).toBeNull();
    expect(
      getChatResponseOutcome({ object: "response", status: "in_progress" }),
    ).toBeNull();
    expect(getChatResponseOutcome("not json")).toBeNull();
  });
});

describe("isPreExecutionConfigurationError", () => {
  it("covers the configuration verdicts only", () => {
    expect(isPreExecutionConfigurationError("MODEL_NOT_CONFIGURED")).toBe(true);
    expect(isPreExecutionConfigurationError("AGENT_CONFIG_UNAVAILABLE")).toBe(
      true,
    );
    expect(isPreExecutionConfigurationError("AGENT_CONFIG_STALE")).toBe(true);
    expect(isPreExecutionConfigurationError("CONFIGURATION_REQUIRED")).toBe(
      true,
    );
    expect(isPreExecutionConfigurationError("CHAT_STREAM_INCOMPLETE")).toBe(
      false,
    );
    expect(isPreExecutionConfigurationError(undefined)).toBe(false);
  });
});

describe("wrapChatResponseOutcomeStream", () => {
  it("passes terminal events through and reports them", async () => {
    const onOutcome = vi.fn();
    const response = wrapChatResponseOutcomeStream(
      sseResponse([`data: ${failedTerminal}\n\n`]),
      { onOutcome },
    );

    const text = await drain(response);

    expect(text).toContain(failedTerminal);
    expect(text).not.toContain("CHAT_STREAM_INCOMPLETE");
    expect(onOutcome).toHaveBeenCalledWith({
      status: "failed",
      errorCode: "MODEL_NOT_CONFIGURED",
      errorMessage: "No active model",
    });
  });

  it("synthesizes a terminal when the stream closed without one", async () => {
    const onOutcome = vi.fn();
    const response = wrapChatResponseOutcomeStream(
      sseResponse(['data: {"type":"turn_usage"}\n\n']),
      { onOutcome },
    );

    const text = await drain(response);

    expect(text).toContain("CHAT_STREAM_INCOMPLETE");
    expect(onOutcome).not.toHaveBeenCalled();
  });

  it("synthesizes a terminal when the transport errors mid-stream", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"object":"response"'));
        controller.error(new Error("connection reset"));
      },
    });
    const response = wrapChatResponseOutcomeStream(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    const text = await drain(response);

    expect(text).toContain("CHAT_STREAM_INCOMPLETE");
  });

  it("leaves non-event-stream responses untouched", async () => {
    const response = new Response(JSON.stringify({ ok: true }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });

    expect(wrapChatResponseOutcomeStream(response)).toBe(response);
  });

  it("keeps the status of the wrapped response", () => {
    const response = wrapChatResponseOutcomeStream(
      sseResponse(["data: {}\n\n"], { status: 200 }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
  });

  it("leaves a partial response shape untouched", () => {
    // Hosts and tests build minimal response objects; the wrapper must not
    // require the whole DOM Response surface to pass them through.
    const partial = { ok: true, status: 200, body: null } as unknown as Response;
    expect(wrapChatResponseOutcomeStream(partial)).toBe(partial);
  });
});

describe("readErrorPayload", () => {
  it("reads a structured error through a clone", async () => {
    const response = new Response(
      JSON.stringify({ detail: { code: "MODEL_NOT_CONFIGURED" } }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
    await expect(readErrorPayload(response)).resolves.toEqual({
      detail: { code: "MODEL_NOT_CONFIGURED" },
    });
    // The original body stays readable for the caller.
    await expect(response.json()).resolves.toEqual({
      detail: { code: "MODEL_NOT_CONFIGURED" },
    });
  });

  it("reads an error from a clone-less response object", async () => {
    const partial = {
      ok: false,
      status: 503,
      json: async () => ({ detail: { code: "AGENT_CONFIG_UNAVAILABLE" } }),
    } as unknown as Response;
    await expect(readErrorPayload(partial)).resolves.toEqual({
      detail: { code: "AGENT_CONFIG_UNAVAILABLE" },
    });
  });

  it("returns null when the body is not JSON", async () => {
    const response = new Response("<html>proxy error</html>", {
      status: 502,
      headers: { "Content-Type": "text/html" },
    });
    await expect(readErrorPayload(response)).resolves.toBeNull();
  });
});
