/**
 * Owns the browser-side response transport used by the current chat turn.
 * The SDK owns a separate AbortController that is not exposed through its ref;
 * this lifecycle gives the page a way to stop buffered SSE events before a
 * canonical server snapshot replaces the visible conversation.
 */
export class ChatTransportLifecycle {
  private current: AbortController | null = null;

  begin(upstream?: AbortSignal): AbortSignal {
    this.abortCurrent();
    const controller = new AbortController();
    this.current = controller;

    if (upstream?.aborted) {
      controller.abort(upstream.reason);
    } else if (upstream) {
      upstream.addEventListener(
        "abort",
        () => controller.abort(upstream.reason),
        { once: true, signal: controller.signal },
      );
    }
    return controller.signal;
  }

  abortCurrent(): void {
    this.current?.abort();
    this.current = null;
  }
}
