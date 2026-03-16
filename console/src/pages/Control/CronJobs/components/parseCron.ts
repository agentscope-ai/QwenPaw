/**
 * Parse cron expression to form-friendly format and vice versa.
 * Supports: hourly, daily, weekly, custom
 *
 * Day-of-week values use three-letter English abbreviations
 * (mon, tue, wed, thu, fri, sat, sun) to avoid the numbering
 * mismatch between crontab (0=Sun) and APScheduler v3 (0=Mon).
 */

export type CronType = "hourly" | "daily" | "weekly" | "custom";

export interface CronParts {
  type: CronType;
  hour?: number;
  minute?: number;
  daysOfWeek?: string[]; // "mon", "tue", …, "sun"
  rawCron?: string;
}

const CRON_RE = /^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$/;
const INTEGER_RE = /^\d+$/;

/**
 * Mapping from crontab numeric day to three-letter abbreviation.
 * Supports both crontab (0=Sun) and the common 7=Sun alias.
 */
const NUM_TO_NAME: Record<string, string> = {
  "0": "sun",
  "1": "mon",
  "2": "tue",
  "3": "wed",
  "4": "thu",
  "5": "fri",
  "6": "sat",
  "7": "sun",
};

const VALID_NAMES = new Set(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]);

/**
 * Parse cron expression to CronParts
 * Examples:
 *   "0 * * * *" -> hourly
 *   "0 9 * * *" -> daily at 09:00
 *   "0 9 * * mon,wed,fri" -> weekly on Mon/Wed/Fri at 09:00
 *   "* /15 * * * *" -> custom (every 15 minutes)
 */
export function parseCron(cron: string): CronParts {
  const trimmed = (cron || "").trim();
  if (!trimmed) {
    return { type: "daily", hour: 9, minute: 0 };
  }

  const match = trimmed.match(CRON_RE);
  if (!match) {
    return { type: "custom", rawCron: trimmed };
  }

  const [, minute, hour, dayOfMonth, month, dayOfWeek] = match;

  // Hourly: "0 * * * *"
  if (
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*" &&
    minute === "0"
  ) {
    return { type: "hourly", minute: 0 };
  }

  // Daily: "M H * * *"
  if (dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
    const h = parsePlainCronNumber(hour, 0, 23);
    const m = parsePlainCronNumber(minute, 0, 59);
    if (h !== null && m !== null) {
      return { type: "daily", hour: h, minute: m };
    }
  }

  // Weekly: "M H * * D" where D is days
  if (dayOfMonth === "*" && month === "*" && dayOfWeek !== "*") {
    const h = parsePlainCronNumber(hour, 0, 23);
    const m = parsePlainCronNumber(minute, 0, 59);
    if (h !== null && m !== null) {
      const days = parseDaysOfWeek(dayOfWeek);
      if (days.length > 0) {
        return { type: "weekly", hour: h, minute: m, daysOfWeek: days };
      }
    }
  }

  // Everything else is custom
  return { type: "custom", rawCron: trimmed };
}

function parsePlainCronNumber(
  value: string,
  min: number,
  max: number,
): number | null {
  if (!INTEGER_RE.test(value)) {
    return null;
  }

  const parsed = Number(value);
  if (parsed < min || parsed > max) {
    return null;
  }

  return parsed;
}

/**
 * Serialize CronParts back to cron expression
 */
export function serializeCron(parts: CronParts): string {
  switch (parts.type) {
    case "hourly":
      return "0 * * * *";

    case "daily": {
      const h = parts.hour ?? 9;
      const m = parts.minute ?? 0;
      return `${m} ${h} * * *`;
    }

    case "weekly": {
      const h = parts.hour ?? 9;
      const m = parts.minute ?? 0;
      const days =
        parts.daysOfWeek && parts.daysOfWeek.length > 0
          ? parts.daysOfWeek.join(",")
          : "mon";
      return `${m} ${h} * * ${days}`;
    }

    case "custom":
      return parts.rawCron || "0 9 * * *";

    default:
      return "0 9 * * *";
  }
}

/**
 * Parse day of week field to string abbreviations.
 *
 * Accepts both numeric (crontab convention: 0=Sun … 6=Sat) and
 * named values (mon, tue, …). Always returns abbreviation strings.
 * Invalid or lossy tokens return an empty array so callers can
 * fall back to `custom`.
 */
function parseDaysOfWeek(dayOfWeek: string): string[] {
  const days: string[] = [];
  const parts = dayOfWeek.split(",");
  const ordered = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

  for (const part of parts) {
    const trimmed = part.trim().toLowerCase();

    if (!trimmed) {
      return [];
    }

    if (VALID_NAMES.has(trimmed)) {
      if (!days.includes(trimmed)) {
        days.push(trimmed);
      }
      continue;
    }

    if (trimmed.includes("-")) {
      const rangeParts = trimmed.split("-");
      if (
        rangeParts.length !== 2 ||
        rangeParts[0] === "" ||
        rangeParts[1] === ""
      ) {
        return [];
      }

      const [startStr, endStr] = rangeParts;
      const startName = NUM_TO_NAME[startStr] || startStr;
      const endName = NUM_TO_NAME[endStr] || endStr;

      if (!VALID_NAMES.has(startName) || !VALID_NAMES.has(endName)) {
        return [];
      }

      const si = ordered.indexOf(startName);
      const ei = ordered.indexOf(endName);
      if (si === -1 || ei === -1 || si > ei) {
        return [];
      }

      for (let i = si; i <= ei; i++) {
        if (!days.includes(ordered[i])) {
          days.push(ordered[i]);
        }
      }
      continue;
    }

    const name = NUM_TO_NAME[trimmed];
    if (!name) {
      return [];
    }

    if (!days.includes(name)) {
      days.push(name);
    }
  }

  return days;
}
