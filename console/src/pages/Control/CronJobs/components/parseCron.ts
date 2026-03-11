/**
 * Parse cron expression to form-friendly format and vice versa.
 * Supports: hourly, daily, weekly, custom
 */

export type CronType = "hourly" | "daily" | "weekly" | "custom";

export interface CronParts {
  type: CronType;
  hour?: number;
  minute?: number;
  daysOfWeek?: number[]; // 0=Sunday, 1=Monday, etc.
  rawCron?: string;
}

const CRON_RE = /^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$/;
const INTEGER_RE = /^(?:0|[1-9]\d*)$/;

/**
 * Parse cron expression to CronParts
 * Examples:
 *   "0 * * * *" -> hourly
 *   "0 9 * * *" -> daily at 09:00
 *   "0 9 * * 1,3,5" -> weekly on Mon/Wed/Fri at 09:00
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
          ? parts.daysOfWeek.sort((a, b) => a - b).join(",")
          : "1"; // default Monday
      return `${m} ${h} * * ${days}`;
    }

    case "custom":
      return parts.rawCron || "0 9 * * *";

    default:
      return "0 9 * * *";
  }
}

/**
 * Parse day of week field (e.g., "1,3,5" or "1-5")
 */
function parseDaysOfWeek(dayOfWeek: string): number[] {
  const days: number[] = [];
  const parts = dayOfWeek.split(",");

  for (const part of parts) {
    if (part.includes("-")) {
      const [startText, endText] = part.split("-");
      const start = parsePlainCronNumber(startText, 0, 6);
      const end = parsePlainCronNumber(endText, 0, 6);
      if (start !== null && end !== null && start <= end) {
        for (let i = start; i <= end; i++) {
          if (i >= 0 && i <= 6 && !days.includes(i)) {
            days.push(i);
          }
        }
      }
    } else {
      const day = parsePlainCronNumber(part, 0, 6);
      if (day !== null && !days.includes(day)) {
        days.push(day);
      }
    }
  }

  return days;
}
