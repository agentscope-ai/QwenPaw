/**
 * Format large numbers in compact form: K (thousands), M (millions), B (billions).
 * e.g. 1500 → "1.5K", 1_200_000 → "1.2M", 999 → "999"
 */
export function formatCompact(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "0";
  const fmt = (v: number) =>
    v % 1 === 0 ? v.toFixed(0) : v.toFixed(1).replace(/\.0$/, "");
  // `toFixed(1)` can round up to 1000 at the top of a band (e.g. 999_999 / 1e3
  // -> "1000.0"), which would render a non-compact "1000K"/"1000M". Promote to
  // the next unit in that case so the output stays compact.
  if (n >= 1e9) return fmt(n / 1e9) + "B";
  if (n >= 1e6)
    return n / 1e6 >= 999.95 ? fmt(n / 1e9) + "B" : fmt(n / 1e6) + "M";
  if (n >= 1e3)
    return n / 1e3 >= 999.95 ? fmt(n / 1e6) + "M" : fmt(n / 1e3) + "K";
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
