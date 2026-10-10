/**
 * Interval polling that pauses while the tab is hidden.
 *
 * Every poll request takes the backend's shared project lock; steady polling
 * from idle/background tabs is exactly the reader stream that starved
 * project writers into 10s LockTimeoutError. Ticks are skipped while the
 * document is hidden and one tick fires immediately when it becomes visible
 * again so the UI catches up without waiting a full interval.
 */
export function startVisiblePolling(
  tick: () => void,
  intervalMs: number,
): () => void {
  const run = () => {
    if (document.hidden) return;
    tick();
  };
  const timer = window.setInterval(run, intervalMs);
  const onVisibilityChange = () => {
    if (!document.hidden) tick();
  };
  document.addEventListener("visibilitychange", onVisibilityChange);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
}
