import { getDateGroup } from "./sessionGrouping";

/**
 * Activity-range filter for the sidebar session list: which sessions
 * count as recent enough to render.
 */
export type SessionActivityFilter = "all" | "today" | "week" | "month";

/** Recency rank of each date bucket (lower = more recent). */
const DATE_GROUP_RANK: Record<ReturnType<typeof getDateGroup>, number> = {
  today: 0,
  week: 1,
  month: 2,
  older: 3,
};

/** Inclusive maximum rank each filter value admits. */
const FILTER_MAX_RANK: Record<SessionActivityFilter, number> = {
  all: 3,
  today: 0,
  week: 1,
  month: 2,
};

interface ActivityTimestamped {
  updatedAt?: string | null;
  createdAt?: string | null;
}

/**
 * Keep sessions whose latest activity falls inside the selected range.
 * Range edges reuse the `getDateGroup` calendar buckets, so "7 days"
 * matches the "Within 7 days" boundary the list already uses elsewhere.
 */
export function filterSessionsByActivity<T extends ActivityTimestamped>(
  sessions: T[],
  filter: SessionActivityFilter,
): T[] {
  if (filter === "all") return sessions;
  const maxRank = FILTER_MAX_RANK[filter];
  return sessions.filter(
    (session) =>
      DATE_GROUP_RANK[getDateGroup(session.updatedAt ?? session.createdAt)] <=
      maxRank,
  );
}
