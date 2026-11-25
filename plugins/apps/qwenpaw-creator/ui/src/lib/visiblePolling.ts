/**
 * Interval polling that pauses while the tab is hidden.
 *
 * Every poll request takes the backend's shared project lock; steady polling
 * from idle/background tabs is exactly the reader stream that starved
 * project writers into 10s LockTimeoutError. Ticks are skipped while the
 * document is hidden and one tick fires immediately when it becomes visible
 * again so the UI catches up without waiting a full interval.
 *
 * The interval may be a function, re-read before every wait. A page that only
 * needs fast updates while something is running should not keep asking every
 * second and a half once it is idle: measured, one Project page ran three
 * independent loops at 1.5-2 s and issued 19 requests in nine seconds, and
 * every one of those answers costs the server a document load and a Task scan.
 * Callers use this to poll fast during activity and slowly at rest.
 */
const MIN_POLL_INTERVAL_MS = 250;

export function startVisiblePolling(
  tick: () => void,
  interval: number | (() => number),
): () => void {
  const nextMs = () =>
    Math.max(
      MIN_POLL_INTERVAL_MS,
      typeof interval === "function" ? interval() : interval,
    );
  let timer = 0;
  let stopped = false;
  const schedule = () => {
    if (stopped) return;
    timer = window.setTimeout(() => {
      if (stopped) return;
      if (!document.hidden) tick();
      schedule();
    }, nextMs());
  };
  const onVisibilityChange = () => {
    if (document.hidden || stopped) return;
    tick();
    window.clearTimeout(timer);
    schedule();
  };
  schedule();
  document.addEventListener("visibilitychange", onVisibilityChange);
  return () => {
    stopped = true;
    window.clearTimeout(timer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
}
