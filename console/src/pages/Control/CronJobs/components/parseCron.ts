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

  // Hourly: "0 * * * *" or "*/N * * * *" where N > 1
  if (
    hour === "*" &&
    dayOfMonth === "*" &&
    month === "*" &&
    dayOfWeek === "*"
  ) {
    if (minute === "0") {
      return { type: "hourly", minute: 0 };
    }
  }

  // Daily: "M H * * *"
  if (dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
    const h = parseInt(hour, 10);
    const m = parseInt(minute, 10);
    if (!isNaN(h) && !isNaN(m) && h >= 0 && h < 24 && m >= 0 && m < 60) {
      return { type: "daily", hour: h, minute: m };
    }
  }

  // Weekly: "M H * * D" where D is days
  if (dayOfMonth === "*" && month === "*" && dayOfWeek !== "*") {
    const h = parseInt(hour, 10);
    const m = parseInt(minute, 10);
    if (!isNaN(h) && !isNaN(m) && h >= 0 && h < 24 && m >= 0 && m < 60) {
      const days = parseDaysOfWeek(dayOfWeek);
      if (days.length > 0) {
        return { type: "weekly", hour: h, minute: m, daysOfWeek: days };
      }
    }
  }

  // Everything else is custom
  return { type: "custom", rawCron: trimmed };
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
          : "mon"; // default Monday
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
 * named values (mon, tue, …).  Always returns abbreviation strings.
 */
function parseDaysOfWeek(dayOfWeek: string): string[] {
  const days: string[] = [];
  const parts = dayOfWeek.split(",");

  for (const part of parts) {
    const trimmed = part.trim().toLowerCase();

    // Try as a name first
    if (VALID_NAMES.has(trimmed)) {
      if (!days.includes(trimmed)) {
        days.push(trimmed);
      }
      continue;
    }

    // Handle ranges like "1-5" or "mon-fri"
    if (trimmed.includes("-")) {
      const [startStr, endStr] = trimmed.split("-");
      const startName = NUM_TO_NAME[startStr] || startStr;
      const endName = NUM_TO_NAME[endStr] || endStr;
      if (VALID_NAMES.has(startName) && VALID_NAMES.has(endName)) {
        // For ranges, expand to individual days
        const ordered = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
        const si = ordered.indexOf(startName);
        const ei = ordered.indexOf(endName);
        if (si !== -1 && ei !== -1) {
          for (let i = si; i <= ei; i++) {
            if (!days.includes(ordered[i])) {
              days.push(ordered[i]);
            }
          }
        }
      }
      continue;
    }

    // Try as a number
    const name = NUM_TO_NAME[trimmed];
    if (name && !days.includes(name)) {
      days.push(name);
    }
  }

  return days;
}
