/**
 * User-issued stop signal for the latest turn of a session.
 *
 * When a turn is stopped *after* its SSE stream already died (dropped
 * connection, proxy kill), the SDK never observes the abort: its stream loop
 * has already exited, so `builder.cancel()` never runs and the response stays
 * at `in_progress` forever. Nothing on the response says the turn is over, so
 * its tool cards would keep spinning until the next reload.
 *
 * The stop click itself is the one reliable fact left, and it is recorded
 * here for the tool-card turn boundary to consume.
 *
 * Validity: the flag only means "this session has no live turn", so every new
 * stream request clears it. That clearing happens on the request path (see
 * `customFetch` / `reconnect`), which no turn can start without — including
 * the SDK's own regenerate, which never passes through the page's UI
 * handlers. Clearing anywhere else would leave a healthy turn's tool calls
 * reported as interrupted.
 */

import { create } from "zustand";
import { resolveBackendSessionId } from "../../utils/resolveBackendSessionId";

interface StoppedTurnsStore {
  /** Backend session id whose latest turn the user stopped. */
  stoppedSessionId: string | null;
}

export const useStoppedTurnsStore = create<StoppedTurnsStore>(() => ({
  stoppedSessionId: null,
}));

/**
 * Record that the user stopped the running turn of the active session.
 *
 * The id is resolved here rather than taken from the caller so it is produced
 * exactly the way the tool-card boundary reads it back; the stopped turn is
 * always the one the user is looking at.
 */
export function markTurnStopped(): void {
  const sessionId = resolveBackendSessionId();
  // An unresolved session id cannot be matched against a card later; skip it
  // rather than storing a flag that would apply to no session at all.
  if (!sessionId) return;
  useStoppedTurnsStore.setState({ stoppedSessionId: sessionId });
}

/** Drop the stop signal because a turn is (re)starting. */
export function clearTurnStopped(): void {
  if (useStoppedTurnsStore.getState().stoppedSessionId === null) return;
  useStoppedTurnsStore.setState({ stoppedSessionId: null });
}
