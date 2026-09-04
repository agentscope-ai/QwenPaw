import { describe, expect, it } from "vitest";

import {
  getChatResponseOutcome,
  isPreExecutionConfigurationError,
  readChatResponseOutcome,
  terminalizeChatResponse,
} from "./chatResponseOutcome";

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

describe("chat response outcomes", () => {
  it.each([
    "MODEL_NOT_CONFIGURED",
    "AGENT_CONFIG_UNAVAILABLE",
    "AGENT_CONFIG_STALE",
    "CONFIGURATION_REQUIRED",
  ])("classifies %s as a pre-execution configuration error", (code) => {
    expect(isPreExecutionConfigurationError(code)).toBe(true);
  });

  it("does not classify an execution failure as safe to restore", () => {
    expect(isPreExecutionConfigurationError("MODEL_EXECUTION_ERROR")).toBe(
      false,
    );
  });

  it("extracts an explicit failed response terminal", () => {
    expect(
      getChatResponseOutcome({
        object: "response",
        status: "failed",
        error: { code: "AGENT_CONFIG_UNAVAILABLE", message: "offline" },
      }),
    ).toEqual({
      status: "failed",
      errorCode: "AGENT_CONFIG_UNAVAILABLE",
      errorMessage: "offline",
    });
  });

  it("reads a completed terminal across CRLF chunk boundaries", async () => {
    const result = await readChatResponseOutcome(
      streamFromChunks([
        'data: {"object":"response","status":"in_progress"}\r\n\r',
        '\ndata: {"object":"response","status":"completed"}',
      ]),
    );
    expect(result).toEqual({
      status: "completed",
      errorCode: undefined,
      errorMessage: undefined,
    });
  });

  it("returns failed rather than treating clean EOF as success", async () => {
    const result = await readChatResponseOutcome(
      streamFromChunks([
        "data: " +
          JSON.stringify({
            object: "response",
            status: "failed",
            error: { code: "AGENT_CONFIG_STALE", message: "reload" },
          }) +
          "\n\n",
      ]),
    );
    expect(result?.status).toBe("failed");
    expect(result?.errorCode).toBe("AGENT_CONFIG_STALE");
  });

  it("returns null when EOF has no response terminal", async () => {
    const result = await readChatResponseOutcome(
      streamFromChunks(['data: {"type":"heartbeat"}\n\n']),
    );
    expect(result).toBeNull();
  });

  it("keeps an explicit terminal when a trailing stream read fails", async () => {
    const encoder = new TextEncoder();
    let pulls = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (pulls === 0) {
          pulls += 1;
          controller.enqueue(
            encoder.encode(
              'data: {"object":"response","status":"completed"}\n\n',
            ),
          );
          return;
        }
        controller.error(new Error("trailing usage disconnected"));
      },
    });

    await expect(readChatResponseOutcome(body)).resolves.toMatchObject({
      status: "completed",
    });
  });

  it("adds an incomplete terminal when a stream ends without one", async () => {
    const response = terminalizeChatResponse(
      new Response(streamFromChunks(['data: {"type":"heartbeat"}\n\n']), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    await expect(readChatResponseOutcome(response.body)).resolves.toEqual({
      status: "failed",
      errorCode: "CHAT_STREAM_INCOMPLETE",
      errorMessage: "Chat stream ended before completion",
    });
  });

  it("adds an incomplete terminal when the response has no body", async () => {
    const response = terminalizeChatResponse(
      new Response(null, { status: 200 }),
    );

    await expect(readChatResponseOutcome(response.body)).resolves.toMatchObject(
      {
        status: "failed",
        errorCode: "CHAT_STREAM_INCOMPLETE",
      },
    );
  });

  it("adds an incomplete terminal when the source stream errors", async () => {
    const encoder = new TextEncoder();
    const source = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"heartbeat"}\n\n'));
        controller.error(new Error("connection lost"));
      },
    });
    const response = terminalizeChatResponse(
      new Response(source, { status: 200 }),
    );

    await expect(readChatResponseOutcome(response.body)).resolves.toMatchObject(
      {
        status: "failed",
        errorCode: "CHAT_STREAM_INCOMPLETE",
      },
    );
  });

  it("does not enqueue after the SDK cancels an in-flight read", async () => {
    const source = new ReadableStream<Uint8Array>({
      pull() {
        return new Promise<void>(() => {
          // Keep the source read pending until the wrapper is cancelled.
        });
      },
    });
    const response = terminalizeChatResponse(
      new Response(source, { status: 200 }),
    );
    const reader = response.body!.getReader();
    const pendingRead = reader.read();

    await reader.cancel("aborted");
    await expect(pendingRead).resolves.toMatchObject({ done: true });
  });
});
