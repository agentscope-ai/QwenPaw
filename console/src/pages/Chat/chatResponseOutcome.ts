import { parseSseDataEvents } from "./sse";

export type ChatResponseStatus = "completed" | "failed";

export interface ChatResponseOutcome {
  status: ChatResponseStatus;
  errorCode?: string;
  errorMessage?: string;
  /**
   * Whether the terminal response carried output. A failure with output
   * happened after the turn started; only a failure without one can mean the
   * turn never ran.
   */
  hasOutput: boolean;
}

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

/**
 * Read a terminal runtime response, or null when the payload is not one.
 *
 * `cancelled` (the wire spelling) is deliberately not a reported outcome: a
 * cancel is not a configuration failure, and the host normalizes the spelling
 * for the SDK in its own response parser.
 */
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
    hasOutput: Array.isArray(record.output) && record.output.length > 0,
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
  const contentType = response.headers?.get?.("content-type") || "";
  if (!contentType.includes("json")) {
    // Only a JSON body can carry a structured code. Never await the body of
    // something else: a non-JSON error stream would never settle.
    return null;
  }
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
 * Report terminal runtime responses seen on the stream. Bytes are forwarded
 * untouched.
 *
 * This observes; it never injects events. A synthetic failure would be
 * indistinguishable from a real one and would take over the SDK's own
 * handling of an interrupted stream, which its disconnected path (and the
 * host's reattach logic) depend on. The backend legitimately ends a stream
 * without a terminal when a reconnect finds no active run.
 */
export function wrapChatResponseOutcomeStream(
  response: Response,
  options: ChatStreamOutcomeOptions = {},
): Response {
  if (!response.body || !isEventStream(response)) {
    return response;
  }

  const source = response.body;
  const reader = source.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let closed = false;

  const inspect = (raw: string) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return;
    }
    const outcome = getChatResponseOutcome(parsed);
    if (outcome) options.onOutcome?.(outcome);
  };

  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (closed) return;

      let done = false;
      let chunk: Uint8Array | undefined;
      try {
        const result = await reader.read();
        done = result.done;
        chunk = result.value;
      } catch (error) {
        // Propagate the transport failure: closing normally would erase the
        // cause and report a generic "ended before a terminal event" instead.
        closed = true;
        controller.error(error);
        return;
      }
      if (closed) return;

      if (done) {
        buffer += decoder.decode();
        // Outside any try: a throw from the caller's callback is a bug in the
        // caller, and swallowing it would hide the missing side effect.
        parseSseDataEvents(buffer, true).events.forEach(inspect);
        closed = true;
        controller.close();
        return;
      }

      if (chunk) {
        controller.enqueue(chunk);
        buffer += decoder.decode(chunk, { stream: true });
        const parsed = parseSseDataEvents(buffer);
        buffer = parsed.rest;
        parsed.events.forEach(inspect);
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
