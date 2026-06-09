/**
 * Format large numbers in compact form: K (thousands), M (millions), B (billions).
 * e.g. 1500 → "1.5K", 1_200_000 → "1.2M", 999 → "999"
 */
export function formatCompact(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "0";
  if (n >= 1e9) {
    const v = n / 1e9;
    return (
      (v % 1 === 0 ? v.toFixed(0) : v.toFixed(1).replace(/\.0$/, "")) + "B"
    );
  }
  if (n >= 1e6) {
    const v = n / 1e6;
    return (
      (v % 1 === 0 ? v.toFixed(0) : v.toFixed(1).replace(/\.0$/, "")) + "M"
    );
  }
  if (n >= 1e3) {
    const v = n / 1e3;
    return (
      (v % 1 === 0 ? v.toFixed(0) : v.toFixed(1).replace(/\.0$/, "")) + "K"
    );
  }
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
