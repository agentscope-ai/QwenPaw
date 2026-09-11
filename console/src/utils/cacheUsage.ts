export function cacheHitRate(
  cacheReadTokens: number,
  cacheEligibleInputTokens: number,
): number | null {
  if (cacheEligibleInputTokens <= 0) return null;
  return Math.max(
    0,
    Math.min((cacheReadTokens / cacheEligibleInputTokens) * 100, 100),
  );
}

export function formatPercent(value: number | null): string {
  if (value === null) return "—";
  if (value > 0 && value < 1) return `${value.toFixed(1)}%`;
  if (value < 100 && Math.round(value) === 100) {
    let precision = 1;
    while (Number(value.toFixed(precision)) === 100) {
      precision += 1;
    }
    return `${value.toFixed(precision)}%`;
  }
  return `${Math.round(value)}%`;
}
