/**
 * Shared session grouping utilities for both SidebarSessionList and ChatSessionDrawer.
 * Groups sessions by date: pinned, today, within 7 days, within 30 days, older.
 */

export type DateGroup = "pinned" | "today" | "week" | "month" | "older";

export interface SessionGroup<T> {
  key: DateGroup;
  label: string;
  sessions: T[];
}

/**
 * Determine which date group a timestamp belongs to.
 * Uses calendar dates (not elapsed-time) so "today" always means the same Y/M/D.
 */
export function getDateGroup(
  timestamp: string | null | undefined,
): Exclude<DateGroup, "pinned"> {
  if (!timestamp) return "older";
  const date = new Date(timestamp);
  if (isNaN(date.getTime())) return "older";

  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dateStart = new Date(
    date.getFullYear(),
    date.getMonth(),
    date.getDate(),
  );
  const calendarDays = Math.floor(
    (todayStart.getTime() - dateStart.getTime()) / (1000 * 60 * 60 * 24),
  );

  if (calendarDays <= 0) return "today";
  if (calendarDays < 7) return "week";
  if (calendarDays < 30) return "month";
  return "older";
}

/**
 * Group sessions by pinned status and date.
 * Pinned sessions go to "pinned" group, others are grouped by date.
 * Empty groups are filtered out.
 */
export function groupSessions<
  T extends {
    pinned?: boolean;
    updatedAt?: string | null;
    createdAt?: string | null;
  },
>(
  sessions: T[],
  t: (key: string, fallback: string) => string,
): SessionGroup<T>[] {
  const buckets: Record<DateGroup, T[]> = {
    pinned: [],
    today: [],
    week: [],
    month: [],
    older: [],
  };

  for (const s of sessions) {
    if (s.pinned) {
      buckets.pinned.push(s);
    } else {
      buckets[getDateGroup(s.updatedAt ?? s.createdAt)].push(s);
    }
  }

  const order: Array<{ key: DateGroup; fallback: string }> = [
    { key: "pinned", fallback: "Pinned" },
    { key: "today", fallback: "Today" },
    { key: "week", fallback: "Within 7 days" },
    { key: "month", fallback: "Within 30 days" },
    { key: "older", fallback: "Earlier" },
  ];

  return order
    .filter(({ key }) => buckets[key].length > 0)
    .map(({ key, fallback }) => ({
      key,
      label: t(`chat.group.${key}`, fallback),
      sessions: buckets[key],
    }));
}
