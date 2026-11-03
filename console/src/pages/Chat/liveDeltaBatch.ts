const RENDER_INTERVAL_MS = 50;
const MAX_DELTA_BYTES = 64 * 1024;

/** Coalesce text only; structural events retain their original ordering. */
export function batchLiveChatDeltas(
  response: Response,
  signal?: AbortSignal,
  interval = RENDER_INTERVAL_MS,
): Response {
  if (!response.body || !response.ok) return response;
  const reader = response.body.getReader();
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  let buffer = "";
  let pending: Record<string, unknown> | undefined;
  let identity: string | undefined;
  let bytes = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let closed = false;
  let abortError: unknown;
  let resume: (() => void) | undefined;
  let abort: () => void = () => undefined;
  const cleanup = () => {
    clearTimeout(timer);
    timer = undefined;
    pending = undefined;
    signal?.removeEventListener("abort", abort);
    resume?.();
    resume = undefined;
  };
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const emit = (frame: string) => {
        if (!closed) controller.enqueue(encoder.encode(`${frame}\n\n`));
      };
      const flush = () => {
        clearTimeout(timer);
        timer = undefined;
        if (pending && !closed) emit(`data: ${JSON.stringify(pending)}`);
        pending = undefined;
        identity = undefined;
        bytes = 0;
      };
      const handle = (frame: string) => {
        // Preserve SSE ids, named events and comments verbatim. They can
        // carry replay/transport semantics that must not be merged away.
        const lines = frame.split("\n");
        let event: Record<string, unknown> | undefined;
        if (lines.length === 1 && lines[0].startsWith("data:")) {
          try {
            event = JSON.parse(lines[0].slice(5));
          } catch {
            // Malformed or non-JSON frames belong to the existing parser.
          }
        }
        if (
          !event ||
          event.object !== "content" ||
          event.type !== "text" ||
          event.delta !== true ||
          typeof event.msg_id !== "string" ||
          typeof event.text !== "string"
        ) {
          flush();
          emit(frame);
          return;
        }
        const { text, ...fields } = event;
        const key = JSON.stringify(
          Object.keys(fields)
            .sort()
            .map((name) => [name, fields[name]]),
        );
        const size = encoder.encode(text).byteLength;
        if (key !== identity || bytes + size > MAX_DELTA_BYTES) flush();
        if (size >= MAX_DELTA_BYTES) {
          emit(frame);
          return;
        }
        if (pending) pending.text = String(pending.text) + text;
        else pending = { ...event };
        identity = key;
        bytes += size;
        timer ??= setTimeout(flush, interval);
      };
      abort = () => {
        if (closed) return;
        // Drain complete frames already received before backpressure paused us.
        let boundary: RegExpExecArray | null;
        while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
          const frame = buffer.slice(0, boundary.index).replace(/\r\n/g, "\n");
          buffer = buffer.slice(boundary.index + boundary[0].length);
          handle(frame);
        }
        flush();
        abortError =
          signal?.reason ?? new DOMException("Aborted", "AbortError");
        closed = true;
        cleanup();
        // Error only after queued text has reached the consumer.
        if ((controller.desiredSize ?? 0) > 0) controller.error(abortError);
        void reader.cancel().catch(() => undefined);
      };
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) {
        abort();
        return;
      }
      void (async () => {
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (closed) return;
            buffer += decoder.decode(value, { stream: !done });
            let boundary: RegExpExecArray | null;
            while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
              const frame = buffer
                .slice(0, boundary.index)
                .replace(/\r\n/g, "\n");
              buffer = buffer.slice(boundary.index + boundary[0].length);
              handle(frame);
              // Stop consuming upstream while the SDK is busy rendering.
              if ((controller.desiredSize ?? 0) <= 0) {
                await new Promise<void>((resolve) => {
                  resume = resolve;
                });
                if (closed) return;
              }
            }
            if (done) break;
          }
          if (buffer.trim()) handle(buffer.replace(/\r\n/g, "\n"));
          flush();
          closed = true;
          controller.close();
        } catch (error) {
          if (!closed) {
            closed = true;
            controller.error(error);
          }
        } finally {
          cleanup();
          await reader.cancel().catch(() => undefined);
        }
      })();
    },
    pull(controller) {
      if (abortError !== undefined) {
        if ((controller.desiredSize ?? 0) > 0) controller.error(abortError);
        return;
      }
      resume?.();
      resume = undefined;
    },
    cancel(reason) {
      closed = true;
      cleanup();
      return reader.cancel(reason);
    },
  });
  return new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}
