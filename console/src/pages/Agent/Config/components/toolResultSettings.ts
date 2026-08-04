export function calculateReserveThreshold(
  maxInputLength: number,
  reserveRatio: number,
): number {
  const requestedReserve = maxInputLength * reserveRatio;
  const minimumRecent = Math.min(10_000, maxInputLength * 0.1);
  return Math.floor(
    Math.min(40_000, Math.max(requestedReserve, minimumRecent)),
  );
}
