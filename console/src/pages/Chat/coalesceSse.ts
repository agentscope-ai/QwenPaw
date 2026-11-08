/**
 * coalesceSse.ts — coalesce streaming response chunks before they reach the
 * chat SDK.
 *
 * The SDK re-renders the conversation for every chunk it receives; with a long
 * session in a split pane that turns into a per-token React render storm. The
 * bytes are preserved exactly (SSE parsers already buffer partial events), so
 * emitting at most one merged chunk per interval keeps streaming smooth while
 * cutting render frequency by an order of magnitude.
 */
export function coalesceSseResponse(
  response: Response,
  intervalMs = 60,
): Response {
  if (!response.body) return response;
  const reader = response.body.getReader();
  let pending: Uint8Array[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = (controller: ReadableStreamDefaultController<Uint8Array>) => {
    if (pending.length === 0) return;
    const total = pending.reduce((sum, chunk) => sum + chunk.length, 0);
    const merged = new Uint8Array(total);
    let offset = 0;
    for (const chunk of pending) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }
    pending = [];
    controller.enqueue(merged);
  };

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          if (value && value.length > 0) pending.push(value);
          if (timer === null) {
            timer = setTimeout(() => {
              timer = null;
              flush(controller);
            }, intervalMs);
          }
        }
        if (timer !== null) {
          clearTimeout(timer);
          timer = null;
        }
        flush(controller);
        controller.close();
      } catch (error) {
        controller.error(error);
      }
    },
    cancel(reason) {
      void reader.cancel(reason);
    },
  });

  return new Response(stream, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}
