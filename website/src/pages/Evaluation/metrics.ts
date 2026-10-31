import type { Row } from "./types";

const group = (row: Row, compareHarnesses: boolean) =>
  compareHarnesses
    ? `${row.provider ?? ""}/${row.model}/${row.harness}`
    : `${row.provider ?? ""}/${row.model}`;
export function bestRows(rows: Row[], compareHarnesses: boolean): Set<string> {
  const best = new Map<string, Row>();
  for (const row of rows.filter((r) => r.score !== null)) {
    const key = group(row, compareHarnesses),
      previous = best.get(key);
    if (
      !previous ||
      row.score! > previous.score! ||
      (row.score === previous.score &&
        (row.cost ?? Infinity) < (previous.cost ?? Infinity)) ||
      (row.score === previous.score &&
        row.cost === previous.cost &&
        row.run.date > previous.run.date)
    )
      best.set(key, row);
  }
  return new Set([...best.values()].map((row) => row.id));
}
export function frontier(rows: Row[]): Row[] {
  return rows
    .filter(
      (r) =>
        r.score !== null &&
        r.cost !== null &&
        r.cost >= 0 &&
        !r.upperBound &&
        !r.partialCost,
    )
    .filter(
      (r, _, candidates) =>
        !candidates.some(
          (other) =>
            other.cost! <= r.cost! &&
            other.score! >= r.score! &&
            (other.cost! < r.cost! || other.score! > r.score!),
        ),
    )
    .sort((a, b) => a.cost! - b.cost!);
}
