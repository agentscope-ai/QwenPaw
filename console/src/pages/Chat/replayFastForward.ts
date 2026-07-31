/**
 * Reconnect fast-forward for replayed SSE streams.
 *
 * On reconnect the backend replays every buffered event of the running
 * turn and then emits a `{"type": "replay_end"}` marker before switching
 * to live events. Feeding the replayed events to the SDK one by one
 * re-animates the whole reply token by token from scratch. This wrapper
 * buffers the response bytes until the marker is seen and hands the
 * replayed section to the SDK as a single chunk, so the already-generated
 * part renders instantly; live events after the marker stream through
 * untouched.
 *
 * Backends without the marker are handled by an idle-timeout fallback:
 * when no new chunk arrives within `idleFlushMs` while still buffering,
 * the buffered bytes are flushed and the stream degrades to passthrough.
 */

/** Raw SSE payload emitted by the backend at the end of a replay. */
const REPLAY_END_EVENT = '{"type": "replay_end"}';

const DEFAULT_IDLE_FLUSH_MS = 300;

/** Unique sentinel for the idle-timeout race. */
const IDLE_TIMEOUT = Symbol("idle-timeout");

function concatChunks(chunks: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const c of chunks) total += c.byteLength;
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) {
    merged.set(c, offset);
    offset += c.byteLength;
  }
  return merged;
}

export function wrapReplayFastForward(
  response: Response,
  idleFlushMs: number = DEFAULT_IDLE_FLUSH_MS,
): Response {
  const body = response.body;
  if (!response.ok || !body) return response;

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffered: Uint8Array[] = [];
  let decoded = "";
  let buffering = true;

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const flush = () => {
        if (!buffering) return;
        buffering = false;
        const merged = concatChunks(buffered);
        buffered = [];
        decoded = "";
        if (merged.byteLength > 0) controller.enqueue(merged);
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
              flush();
              continue;
            }
            result = winner;
          } else {
            result = await readPromise;
          }
          pendingRead = null;

          if (result.done) {
            flush();
            break;
          }
          if (!buffering) {
            controller.enqueue(result.value);
            continue;
          }
          buffered.push(result.value);
          decoded += decoder.decode(result.value, { stream: true });
          if (decoded.includes(REPLAY_END_EVENT)) flush();
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
