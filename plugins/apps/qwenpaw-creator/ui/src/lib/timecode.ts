/**
 * Shared seconds formatting for timeline surfaces (tracks, canvas, lists).
 * Two decimals with trailing zeros trimmed, so a 4.95s boundary never reads
 * as 5s and every surface shows the same persisted tick value.
 */
export function formatSeconds(tick: number, ticksPerSecond: number): string {
  return (tick / Math.max(1, ticksPerSecond))
    .toFixed(2)
    .replace(/0+$/, "")
    .replace(/\.$/, "");
}
