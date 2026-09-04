import { parseSseDataEvents } from "./sse";

export type ChatResponseStatus = "completed" | "failed";

export interface ChatResponseOutcome {
  status: ChatResponseStatus;
  errorCode?: string;
  errorMessage?: string;
}

const INCOMPLETE_STREAM_ERROR = {
  object: "response",
  status: "failed",
  error: {
    code: "CHAT_STREAM_INCOMPLETE",
    message: "Chat stream ended before completion",
  },
};

const PRE_EXECUTION_CONFIGURATION_ERRORS = new Set([
  "MODEL_NOT_CONFIGURED",
  "AGENT_CONFIG_UNAVAILABLE",
  "AGENT_CONFIG_STALE",
  "CONFIGURATION_REQUIRED",
]);

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

function readErrorField(
  payload: unknown,
  field: "code" | "message",
): string | undefined {
  const record = asRecord(payload);
  if (!record) return undefined;
  for (const candidate of [record.error, record.detail, record]) {
    const nested = asRecord(candidate);
    if (typeof nested?.[field] === "string") {
      return nested[field] as string;
    }
  }
  return undefined;
}

export function getChatErrorCode(payload: unknown): string | undefined {
  return readErrorField(payload, "code");
}

export function isModelNotConfiguredError(payload: unknown): boolean {
  return getChatErrorCode(payload) === "MODEL_NOT_CONFIGURED";
}

export function getChatResponseOutcome(
  payload: unknown,
): ChatResponseOutcome | null {
  const record = asRecord(payload);
  if (
    record?.object !== "response" ||
    (record.status !== "completed" && record.status !== "failed")
  ) {
    return null;
  }
  return {
    status: record.status,
    errorCode: getChatErrorCode(record),
    errorMessage: readErrorField(record, "message"),
  };
}

export function isPreExecutionConfigurationError(
  errorCode: string | undefined,
): boolean {
  return !!errorCode && PRE_EXECUTION_CONFIGURATION_ERRORS.has(errorCode);
}

/** Drain an SSE response and return its last explicit response terminal. */
export async function readChatResponseOutcome(
  body: ReadableStream<Uint8Array> | null,
): Promise<ChatResponseOutcome | null> {
  if (!body) return null;

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal: ChatResponseOutcome | null = null;

  const consume = (events: string[]) => {
    for (const raw of events) {
      try {
        const outcome = getChatResponseOutcome(JSON.parse(raw));
        if (outcome) terminal = outcome;
      } catch {
        // Ignore malformed/non-JSON events and keep draining the response.
      }
    }
  };

  for (;;) {
    let result: ReadableStreamReadResult<Uint8Array>;
    try {
      result = await reader.read();
    } catch (error) {
      if (terminal) return terminal;
      throw error;
    }
    const { done, value } = result;
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseDataEvents(buffer);
    buffer = parsed.rest;
    consume(parsed.events);
  }

  buffer += decoder.decode();
  consume(parseSseDataEvents(buffer, true).events);
  return terminal;
}

/**
 * Ensure a streaming client receives a terminal event even when the transport
 * closes without one. The SDK uses terminal events to leave the loading state.
 */
export function terminalizeChatResponse(response: Response): Response {
  const encoder = new TextEncoder();
  const terminalEvent = encoder.encode(
    `data: ${JSON.stringify(INCOMPLETE_STREAM_ERROR)}\n\n`,
  );

  if (!response.body) {
    const headers = new Headers(response.headers);
    headers.set("Content-Type", "text/event-stream");
    return new Response(terminalEvent, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  }

  const source = response.body;
  const reader = source.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminal: ChatResponseOutcome | null = null;
  let closed = false;

  const consume = (events: string[]) => {
    for (const raw of events) {
      try {
        const outcome = getChatResponseOutcome(JSON.parse(raw));
        if (outcome) terminal = outcome;
      } catch {
        // Ignore malformed events; the SDK will still receive a terminal.
      }
    }
  };

  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (closed) return;
      try {
        const result = await reader.read();
        if (closed) return;
        if (!result.done) {
          controller.enqueue(result.value);
          buffer += decoder.decode(result.value, { stream: true });
          const parsed = parseSseDataEvents(buffer);
          buffer = parsed.rest;
          consume(parsed.events);
          return;
        }

        buffer += decoder.decode();
        consume(parseSseDataEvents(buffer, true).events);
        if (!terminal) controller.enqueue(terminalEvent);
        closed = true;
        controller.close();
      } catch {
        if (closed) return;
        if (!terminal) controller.enqueue(terminalEvent);
        closed = true;
        controller.close();
      }
    },
    cancel(reason) {
      closed = true;
      void reader.cancel(reason).catch(() => {
        // The source may already be closed when the SDK aborts the wrapper.
      });
    },
  });

  const headers = new Headers(response.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "text/event-stream");
  }
  return new Response(stream, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}
