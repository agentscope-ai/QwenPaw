/**
 * Parse backend "every" string (e.g. "6h", "30m", "2h30m") to number + unit
 * for form display. Serialize back to string for API.
 */

const EVERY_RE =
  /^(?:(?<hours>\d+)h)?(?:(?<minutes>\d+)m)?(?:(?<seconds>\d+)s)?$/i;

export type EveryUnit = "m" | "h";

export interface EveryParts {
  number: number;
  unit: EveryUnit;
}

export function parseEvery(every: string): EveryParts {
  const s = (every || "").trim();
  if (!s) {
    return { number: 6, unit: "h" };
  }
  const m = s.match(EVERY_RE);
  if (!m || !m.groups) {
    return { number: 6, unit: "h" };
  }
  const hours = parseInt(m.groups.hours ?? "0", 10);
  const minutes = parseInt(m.groups.minutes ?? "0", 10);
  const seconds = parseInt(m.groups.seconds ?? "0", 10);
  const totalMinutes = hours * 60 + minutes + Math.round(seconds / 60);
  if (totalMinutes <= 0) {
    return { number: 6, unit: "h" };
  }
  if (totalMinutes >= 60 && totalMinutes % 60 === 0) {
    return { number: totalMinutes / 60, unit: "h" };
  }
  return { number: totalMinutes, unit: "m" };
}

export function serializeEvery(parts: EveryParts): string {
  if (parts.unit === "h") {
    return `${parts.number}h`;
  }
  return `${parts.number}m`;
}
