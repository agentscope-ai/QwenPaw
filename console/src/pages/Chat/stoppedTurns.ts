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
 * Validity: each entry only means "this session has no live turn", so a new
 * stream request clears that session's entry. That clearing happens on the
 * request path (see `customFetch` / `reconnect`), which no turn can start
 * without — including the SDK's own regenerate, which never passes through
 * the page's UI handlers. Clearing anywhere else would leave a healthy turn's
 * tool calls reported as interrupted.
 */

import { create } from "zustand";
import { resolveBackendSessionId } from "../../utils/resolveBackendSessionId";

interface StoppedTurnsStore {
  /** Backend-compatible runtime session ids stopped by the user. */
  stoppedSessionIds: ReadonlySet<string>;
}

export const useStoppedTurnsStore = create<StoppedTurnsStore>(() => ({
  stoppedSessionIds: new Set(),
}));

/**
 * Record that the user stopped the running turn of the requested session.
 */
export function markTurnStopped(targetSessionId?: string | null): void {
  const target = targetSessionId?.trim();
  if (!target) return;
  const sessionId = resolveBackendSessionId(target);
  // An unresolved session id cannot be matched against a card later; skip it
  // rather than storing a flag that would apply to no session at all.
  if (!sessionId) return;
  const current = useStoppedTurnsStore.getState().stoppedSessionIds;
  if (current.has(sessionId)) return;
  useStoppedTurnsStore.setState({
    stoppedSessionIds: new Set([...current, sessionId]),
  });
}

/** Drop one session's stop signal because its turn is (re)starting. */
export function clearTurnStopped(targetSessionId: string): void {
  const target = targetSessionId.trim();
  if (!target) return;
  const sessionId = resolveBackendSessionId(target);
  if (!sessionId) return;
  const current = useStoppedTurnsStore.getState().stoppedSessionIds;
  if (!current.has(sessionId)) return;
  const next = new Set(current);
  next.delete(sessionId);
  useStoppedTurnsStore.setState({ stoppedSessionIds: next });
}
