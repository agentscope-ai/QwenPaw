/**
 * Registry of background queue AbortControllers.
 *
 * Extracted from Chat/index.tsx (was module-private `_bgAborts` /
 * `stopBackgroundQueue`) so the stop/reset contract can be unit-tested.
 * Behaviour is unchanged: the background sender keeps draining the message
 * queue after ChatPage unmounts, one controller per session.
 *
 * Regressions guarded here:
 * - #505: after stopping, the sender's state must be fully reset — the
 *   controller is aborted AND removed from the registry, so a subsequent
 *   send can start a fresh sender instead of hitting the stale aborted one
 *   ("Answer has been stopped" until page refresh).
 */

const _bgAborts = new Map<string, AbortController>();

/**
 * Stop background sending.
 * - with queueKey: abort + unregister that session's sender only;
 * - without: abort + unregister every sender (full cleanup).
 * After stopping, `getBackgroundAbort(key)` no longer returns the old
 * controller — callers treat that as "safe to start a new sender".
 */
export function stopBackgroundQueue(queueKey?: string): void {
  if (queueKey) {
    const ctrl = _bgAborts.get(queueKey);
    if (ctrl) {
      ctrl.abort();
      _bgAborts.delete(queueKey);
    }
  } else {
    for (const ctrl of _bgAborts.values()) {
      ctrl.abort();
    }
    _bgAborts.clear();
  }
}

/** Returns the live AbortController for a running sender, if any. */
export function getBackgroundAbort(
  queueKey: string,
): AbortController | undefined {
  return _bgAborts.get(queueKey);
}

/** Registers the sender's controller for a session (replaces any old one). */
export function setBackgroundAbort(
  queueKey: string,
  ctrl: AbortController,
): void {
  _bgAborts.set(queueKey, ctrl);
}

/** Removes the registration only if it is still the given controller. */
export function clearBackgroundAbortIfCurrent(
  queueKey: string,
  ctrl: AbortController,
): void {
  if (_bgAborts.get(queueKey) === ctrl) _bgAborts.delete(queueKey);
}

/** Whether a sender is registered for the session. */
export function hasBackgroundQueue(queueKey: string): boolean {
  return _bgAborts.has(queueKey);
}

/** Test hook: drop all registrations without aborting. */
export function resetBackgroundQueueRegistryForTests(): void {
  _bgAborts.clear();
}
