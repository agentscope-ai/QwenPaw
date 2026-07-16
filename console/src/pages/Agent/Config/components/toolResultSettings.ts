export function usesTieredToolResultSettings(
  strategy: string | undefined,
): boolean {
  return strategy === "native";
}

export function calculateReserveThreshold(
  maxInputLength: number,
  reserveRatio: number,
  strategy: string | undefined,
): number {
  const requestedReserve = maxInputLength * reserveRatio;
  if (strategy === "native") {
    return Math.floor(requestedReserve);
  }

  const minimumRecent = Math.min(10_000, maxInputLength * 0.1);
  return Math.floor(
    Math.min(40_000, Math.max(requestedReserve, minimumRecent)),
  );
}
