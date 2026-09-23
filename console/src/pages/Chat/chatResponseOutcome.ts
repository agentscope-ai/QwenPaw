import { parseSseDataEvents } from "./sse";

export type ChatResponseStatus = "completed" | "failed";

export interface ChatResponseOutcome {
  status: ChatResponseStatus;
  errorCode?: string;
  errorMessage?: string;
}

const INCOMPLETE_STREAM_EVENT = {
  object: "response",
  status: "failed",
  error: {
    code: "CHAT_STREAM_INCOMPLETE",
    message: "Chat stream ended before completion",
  },
};

/**
 * Failures that mean the turn never started, so the client may roll the user
 * message back and, for a missing model, offer the configuration prompt.
 */
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
  if (!record || record.object !== "response") return null;

  const status = record.status;
  if (status !== "completed" && status !== "failed") return null;

  return {
    status,
    errorCode: getChatErrorCode(record),
    errorMessage: readErrorField(record, "message"),
  };
}

export function isPreExecutionConfigurationError(
  errorCode: string | undefined,
): boolean {
  return !!errorCode && PRE_EXECUTION_CONFIGURATION_ERRORS.has(errorCode);
}

export interface ChatStreamOutcomeOptions {
  /** Called once per terminal event the backend actually sent. */
  onOutcome?: (outcome: ChatResponseOutcome) => void;
}

function isEventStream(response: Response): boolean {
  const contentType = response.headers?.get?.("content-type") || "";
  return contentType.includes("text/event-stream");
}

/**
 * Read an error body without consuming the response callers may still read.
 */
export async function readErrorPayload(response: Response): Promise<unknown> {
  try {
    if (typeof response.clone === "function") {
      return await response.clone().json();
    }
    if (typeof response.json === "function") {
      return await response.json();
    }
  } catch {
    // A proxy page or an empty 5xx body carries no structured code.
  }
  return null;
}

/**
 * Observe the response stream and guarantee a terminal event.
 *
 * The SDK leaves its loading state on a terminal `{object: "response"}` event.
 * A dropped connection, a proxy rewrite or a backend crash can close the
 * transport without one, which would strand the turn in "loading" forever, so
 * synthesize an explicit incomplete-stream failure in that case. Chunks are
 * forwarded untouched; only the missing terminal is appended.
 */
export function wrapChatResponseOutcomeStream(
  response: Response,
  options: ChatStreamOutcomeOptions = {},
): Response {
  if (!response.body || !isEventStream(response)) {
    return response;
  }

  const encoder = new TextEncoder();
  const source = response.body;
  const reader = source.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let seenTerminal = false;
  let closed = false;

  const inspect = (raw: string) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }
    const outcome = getChatResponseOutcome(parsed);
    if (!outcome) return;
    seenTerminal = true;
    options.onOutcome?.(outcome);
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
          parsed.events.forEach(inspect);
          return;
        }

        buffer += decoder.decode();
        parseSseDataEvents(buffer, true).events.forEach(inspect);
        if (!seenTerminal) {
          controller.enqueue(
            encoder.encode(
              `data: ${JSON.stringify(INCOMPLETE_STREAM_EVENT)}\n\n`,
            ),
          );
        }
        closed = true;
        controller.close();
      } catch {
        if (closed) return;
        if (!seenTerminal) {
          controller.enqueue(
            encoder.encode(
              `data: ${JSON.stringify(INCOMPLETE_STREAM_EVENT)}\n\n`,
            ),
          );
        }
        closed = true;
        controller.close();
      }
    },
    cancel(reason) {
      closed = true;
      void reader.cancel(reason).catch(() => {
        // The source is usually already closed when the SDK aborts us.
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
