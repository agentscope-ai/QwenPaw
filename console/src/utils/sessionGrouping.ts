/**
 * Session grouping utilities for SidebarSessionList.
 * Groups sessions by date: pinned, today, within 7 days, within 30 days, older.
 */

export type DateGroup = "pinned" | "today" | "week" | "month" | "older";

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
 * Locate a session inside the flattened (group header + session) rows
 * of the virtualized session lists. Rows inside collapsed groups are
 * not present, so a -1 result also means "not currently visible".
 */
export function findSessionRowIndex(
  rows: Array<{
    kind: string;
    session?: { id?: string; realId?: string };
  }>,
  sessionId: string | undefined,
): number {
  if (!sessionId) return -1;
  return rows.findIndex(
    (row) =>
      row.kind === "session" &&
      (row.session?.id === sessionId || row.session?.realId === sessionId),
  );
}
