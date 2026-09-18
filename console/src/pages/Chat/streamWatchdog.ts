/**
 * Stream-death watchdog for the Chat page.
 *
 * The SDK only issues a reconnect when a session is (re)mounted while the
 * backend reports it generating (the `handleReconnect` DOM event). If the
 * SSE stream dies mid-run — proxy idle timeout, gateway cut, laptop sleep —
 * nothing re-triggers it, so the UI spins forever even though the backend
 * finished long ago (a manual reload shows the completed turn).
 *
 * This module recovers that state:
 *
 * - `createStreamTracker()` counts in-flight `/console/chat` response
 *   bodies (both the send and the reconnect path wrap their Response in
 *   `tracker.trackResponse()`); a body that ends, errors or is cancelled
 *   releases its slot.
 * - The page flips `setRunningTurn(true)` when a send starts and flips it
 *   back when the event stream reports a terminal status, so the watchdog
 *   knows the UI *believes* a turn is in progress.
 * - `createStreamWatchdog()` polls while a turn is believed running: with
 *   no active stream past the cooldown it asks the backend whether the
 *   session is still generating and dispatches `handleReconnect` — the
 *   exact event the SDK's mount path uses. A still-generating session
 *   re-attaches (replay + live); a finished one makes the SDK fall back
 *   to the persisted history, which ends the spinner.
 */

export const HANDLE_RECONNECT_EVENT = "handleReconnect";

/** Cooldown between watchdog-triggered reconnects. */
const RECONNECT_COOLDOWN_MS = 8_000;
/** Poll cadence while a turn is believed running. */
export const POLL_INTERVAL_MS = 5_000;
/** Quiet period right after a send, before the watchdog may act. */
const QUIET_AFTER_SEND_MS = 15_000;
/** Max reconnect attempts once the backend says the run has finished. */
const MAX_FINISHED_ATTEMPTS = 2;
/** Hard cap per turn so a permanently unreachable backend cannot loop. */
const MAX_TOTAL_ATTEMPTS = 60;

export interface StreamTracker {
  /** Number of tracked response bodies still streaming. */
  activeCount(): number;
  /** Wrap a Response so its body lifecycle is tracked. Pass-through. */
  trackResponse(response: Response): Response;
}

export function createStreamTracker(): StreamTracker {
  let active = 0;

  const wrapBody = (body: ReadableStream<Uint8Array>) => {
    const reader = body.getReader();
    return new ReadableStream<Uint8Array>({
      async start(controller) {
        active += 1;
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            controller.enqueue(value);
          }
          controller.close();
        } catch (err) {
          controller.error(err);
        } finally {
          active = Math.max(0, active - 1);
        }
      },
      cancel(reason) {
        active = Math.max(0, active - 1);
        return reader.cancel(reason);
      },
    });
  };

  return {
    activeCount: () => active,
    trackResponse(response: Response): Response {
      if (!response.ok || !response.body) return response;
      return new Response(wrapBody(response.body), {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers,
      });
    },
  };
}

export interface StreamWatchdogOptions {
  /** True while the UI believes a turn is running. */
  isRunningTurn(): boolean;
  /** Number of in-flight chat streams (0 = the stream is dead). */
  activeStreamCount(): number;
  /** Ask the backend whether the session is still generating. */
  isSessionGenerating(): Promise<boolean>;
  /** Fire the SDK's reconnect path for the current session. */
  requestReconnect(): void;
  /** Wall-clock ms of the last send; injectable for tests. */
  lastSendAt(): number;
  /** Wall-clock ms; injectable for tests. */
  now?(): number;
}

export interface StreamWatchdog {
  /** Reset attempt counters (the page calls this on every new send). */
  reset(): void;
  /** Call once per poll tick (the page wires an interval). */
  tick(): Promise<void>;
}

export function createStreamWatchdog(
  options: StreamWatchdogOptions,
): StreamWatchdog {
  const {
    isRunningTurn,
    activeStreamCount,
    isSessionGenerating,
    requestReconnect,
    lastSendAt,
    now = () => Date.now(),
  } = options;

  let lastReconnectAt = 0;
  let finishedAttempts = 0;
  let totalAttempts = 0;
  let inFlight = false;

  return {
    /** Reset attempt counters (the page calls this on every new send). */
    reset() {
      finishedAttempts = 0;
      totalAttempts = 0;
    },
    async tick(): Promise<void> {
      if (inFlight) return;
      if (!isRunningTurn()) return;
      if (activeStreamCount() > 0) return;

      const t = now();
      if (t - lastSendAt() < QUIET_AFTER_SEND_MS) return;
      if (t - lastReconnectAt < RECONNECT_COOLDOWN_MS) return;
      if (finishedAttempts >= MAX_FINISHED_ATTEMPTS) return;
      if (totalAttempts >= MAX_TOTAL_ATTEMPTS) return;

      inFlight = true;
      try {
        const generating = await isSessionGenerating();
        if (!isRunningTurn() || activeStreamCount() > 0) return;
        lastReconnectAt = now();
        totalAttempts += 1;
        if (!generating) {
          finishedAttempts += 1;
        }
        requestReconnect();
      } catch {
        // Status probe failed (network blip) — try again next tick.
      } finally {
        inFlight = false;
      }
    },
  };
}

/**
 * Page-owned "the UI believes a turn is running" state.
 *
 * `markSend()` flips the flag on and stamps the quiet window; the event
 * parser flips it off when the stream reports a terminal status.
 */
export function createTurnRunningState() {
  let running = false;
  let sentAt = 0;
  return {
    get: () => running,
    markSend() {
      running = true;
      sentAt = Date.now();
    },
    clear() {
      running = false;
    },
    lastSendAt: () => sentAt,
  };
}

export type TurnRunningState = ReturnType<typeof createTurnRunningState>;
