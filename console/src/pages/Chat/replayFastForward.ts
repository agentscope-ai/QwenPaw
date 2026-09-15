/**
 * Reconnect fast-forward for replayed SSE streams.
 *
 * On reconnect the backend replays every buffered event of the running
 * turn and then emits a `{"type": "replay_end"}` marker before switching
 * to live events. Feeding the replayed events to the SDK one by one
 * re-animates the whole reply token by token from scratch. This wrapper
 * re-frames the stream on SSE event boundaries, buffers everything until
 * the marker and hands the replayed section to the SDK as a single chunk,
 * so the already-generated part renders instantly; live events after the
 * marker stream through untouched.
 *
 * The marker itself is stripped here at the byte level and never reaches
 * the SDK: its response builder dereferences `data.object` on every
 * parsed event, and an unknown payload throws mid-stream, killing all
 * subsequent live tokens.
 *
 * Backends without the marker are handled by an idle-timeout fallback:
 * when no new chunk arrives within `idleFlushMs` while still buffering,
 * the buffered events are flushed and the stream degrades to passthrough
 * (late markers are still filtered out).
 */

/** Exact SSE event emitted by the backend at the end of a replay. */
const REPLAY_END_EVENT = 'data: {"type": "replay_end"}';

const DEFAULT_IDLE_FLUSH_MS = 300;

/** Unique sentinel for the idle-timeout race. */
const IDLE_TIMEOUT = Symbol("idle-timeout");

const isMarker = (event: string): boolean => event.trim() === REPLAY_END_EVENT;

/** Split buffered text into complete SSE events and the partial tail. */
function splitEvents(buf: string): { events: string[]; rest: string } {
  const parts = buf.split("\n\n");
  const rest = parts.pop() ?? "";
  return { events: parts.filter((e) => e.length > 0), rest };
}

export function wrapReplayFastForward(
  response: Response,
  idleFlushMs: number = DEFAULT_IDLE_FLUSH_MS,
): Response {
  const body = response.body;
  if (!response.ok || !body) return response;

  const reader = body.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  /** Decoded text still missing its `\n\n` event terminator. */
  let textBuf = "";
  /** Complete replayed events awaiting the single fast-forward flush. */
  let replayEvents: string[] = [];
  let buffering = true;

  const encodeEvents = (events: string[]): Uint8Array =>
    encoder.encode(events.map((e) => `${e}\n\n`).join(""));

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const flushReplay = () => {
        buffering = false;
        const out = replayEvents.filter((e) => !isMarker(e));
        replayEvents = [];
        if (out.length > 0) controller.enqueue(encodeEvents(out));
      };

      // Held across loop iterations so an idle-timeout never leaves a
      // dangling read() racing a second concurrent read() call.
      let pendingRead: Promise<ReadableStreamReadResult<Uint8Array>> | null =
        null;

      try {
        for (;;) {
          const readPromise: Promise<ReadableStreamReadResult<Uint8Array>> =
            pendingRead ?? reader.read();
          pendingRead = readPromise;

          let result: ReadableStreamReadResult<Uint8Array>;
          if (buffering) {
            let timer: ReturnType<typeof setTimeout> | undefined;
            const timeout = new Promise<typeof IDLE_TIMEOUT>((resolve) => {
              timer = setTimeout(() => resolve(IDLE_TIMEOUT), idleFlushMs);
            });
            const winner = await Promise.race([readPromise, timeout]);
            clearTimeout(timer);
            if (winner === IDLE_TIMEOUT) {
              // No marker within the window (old backend or the replay
              // already reached the live edge): degrade to passthrough.
              flushReplay();
              continue;
            }
            result = winner;
          } else {
            result = await readPromise;
          }
          pendingRead = null;

          if (result.done) {
            // Emit everything still held: buffered replay events, any
            // complete events in the tail, and the partial tail as-is.
            textBuf += decoder.decode();
            const { events, rest } = splitEvents(textBuf);
            const out = [...replayEvents, ...events].filter(
              (e) => !isMarker(e),
            );
            replayEvents = [];
            const payload = out.map((e) => `${e}\n\n`).join("") + rest;
            if (payload) controller.enqueue(encoder.encode(payload));
            break;
          }

          textBuf += decoder.decode(result.value, { stream: true });
          const { events, rest } = splitEvents(textBuf);
          textBuf = rest;

          if (buffering) {
            let sawMarker = false;
            for (const event of events) {
              if (isMarker(event)) sawMarker = true;
              else replayEvents.push(event);
            }
            if (sawMarker) flushReplay();
          } else {
            const out = events.filter((e) => !isMarker(e));
            if (out.length > 0) controller.enqueue(encodeEvents(out));
          }
        }
        controller.close();
      } catch (err) {
        controller.error(err);
      }
    },
    cancel(reason) {
      return reader.cancel(reason);
    },
  });

  return new Response(stream, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}
