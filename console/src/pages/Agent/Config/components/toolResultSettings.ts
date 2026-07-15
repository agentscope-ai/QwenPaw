export function usesTieredToolResultSettings(
  strategy: string | undefined,
): boolean {
  return strategy === "native";
}
