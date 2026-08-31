/**
 * Session display-time helpers for the session list drawer.
 *
 * Extracted from ChatSessionDrawer/index.tsx so the time-display contract
 * can be unit-tested without rendering the drawer. Behaviour is unchanged;
 * the formatting cache stays with the component.
 *
 * Regressions guarded here:
 * - #769: the session list showed the creation time where the update time
 *   belongs (fields appeared swapped). The contract: prefer the update
 *   timestamp, fall back to creation only when there is no update.
 */

export interface SessionTimestamps {
  createdAt?: string | null;
  updatedAt?: string | null;
}

/**
 * Picks the timestamp to display for a session row.
 *
 * Updated time wins; creation time is only a fallback for sessions that were
 * never updated. Keeping the two apart matters: showing the creation time on
 * an updated session makes it look like the conversation never changed (#769).
 */
export function pickSessionDisplayTime(
  session: SessionTimestamps,
): string | null {
  return session.updatedAt ?? session.createdAt ?? null;
}

/**
 * Formats a raw timestamp as local "YYYY-MM-DD HH:mm:ss".
 * Returns "" for missing or unparseable input so the UI renders an empty
 * cell instead of "Invalid Date".
 */
export function formatSessionTime(raw: string | null | undefined): string {
  if (!raw) return "";
  const date = new Date(raw);
  if (isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
    date.getSeconds(),
  )}`;
}
