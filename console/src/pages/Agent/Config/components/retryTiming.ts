export function retryDelays(count: number, base: number, cap: number) {
  return Array.from(
    { length: Math.max(0, Math.min(8, Math.floor(count))) },
    (_, index) => Math.min(cap, base * 2 ** index),
  );
}
