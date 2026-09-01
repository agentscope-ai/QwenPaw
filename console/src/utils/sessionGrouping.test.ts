/**
 * findSessionRowIndex locates the active conversation inside the
 * flattened (group header + session) row list used by the virtualized
 * session lists, so they can scroll it into view after remount.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import {
  findSessionRowIndex,
  getDateGroup,
  groupSessions,
} from "./sessionGrouping";

const rows = [
  { kind: "groupHeader" as const },
  { kind: "session" as const, session: { id: "a" } },
  { kind: "session" as const, session: { id: "local-1", realId: "b" } },
  { kind: "groupHeader" as const },
  { kind: "session" as const, session: { id: "c" } },
];

describe("findSessionRowIndex", () => {
  it("finds a session row by id", () => {
    expect(findSessionRowIndex(rows, "c")).toBe(4);
  });

  it("finds a session row by realId (local timestamp entries)", () => {
    expect(findSessionRowIndex(rows, "b")).toBe(2);
  });

  it("returns -1 when the session is not in the visible rows", () => {
    expect(findSessionRowIndex(rows, "hidden")).toBe(-1);
  });

  it("returns -1 for an undefined session id", () => {
    expect(findSessionRowIndex(rows, undefined)).toBe(-1);
  });

  it("never matches a group header row", () => {
    expect(findSessionRowIndex([{ kind: "groupHeader" }], "a")).toBe(-1);
  });
});

/**
 * getDateGroup buckets sessions by calendar day distance (not elapsed
 * hours), so "today" always means the same Y/M/D for the user.
 * Regression: elapsed-time bucketing drifts sessions across groups as
 * the day progresses (#6871-style timestamp instability family).
 */
describe("getDateGroup", () => {
  // Freeze "now" at 2026-01-15 10:00 local
  beforeEach(() => {
    vi.setSystemTime(new Date(2026, 0, 15, 10, 0, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("puts today's sessions in the today group regardless of time", () => {
    expect(getDateGroup("2026-01-15T00:00:00")).toBe("today");
    expect(getDateGroup("2026-01-15T23:59:00")).toBe("today");
  });

  it("puts sessions 1-6 calendar days back in the week group", () => {
    expect(getDateGroup("2026-01-14T23:00:00")).toBe("week");
    expect(getDateGroup("2026-01-09T10:00:00")).toBe("week");
  });

  it("puts sessions 7-29 calendar days back in the month group", () => {
    expect(getDateGroup("2026-01-08T10:00:00")).toBe("month");
    expect(getDateGroup("2025-12-17T10:00:00")).toBe("month");
  });

  it("puts sessions 30+ calendar days back in the older group", () => {
    expect(getDateGroup("2025-12-16T10:00:00")).toBe("older");
    expect(getDateGroup("2024-06-01T10:00:00")).toBe("older");
  });

  it("puts future-dated sessions in today (clock skew tolerance)", () => {
    expect(getDateGroup("2026-01-16T08:00:00")).toBe("today");
  });

  it("puts missing or unparseable timestamps in the older group", () => {
    expect(getDateGroup(null)).toBe("older");
    expect(getDateGroup(undefined)).toBe("older");
    expect(getDateGroup("")).toBe("older");
    expect(getDateGroup("not-a-date")).toBe("older");
  });
});

/**
 * groupSessions: pinned sessions always lead, remaining sessions fall
 * into date buckets, and empty buckets are omitted from the output.
 */
describe("groupSessions", () => {
  beforeEach(() => {
    vi.setSystemTime(new Date(2026, 0, 15, 10, 0, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const t = (_key: string, fallback: string) => fallback;

  it("pins pinned sessions into the pinned group first", () => {
    const groups = groupSessions(
      [
        { id: "old-pinned", pinned: true, updatedAt: "2020-01-01T00:00:00" },
        { id: "fresh", updatedAt: "2026-01-15T09:00:00" },
      ],
      t,
    );
    expect(groups[0].key).toBe("pinned");
    expect(groups[0].sessions.map((s) => s.id)).toEqual(["old-pinned"]);
    expect(groups[1].key).toBe("today");
  });

  it("groups by date and drops empty buckets", () => {
    const groups = groupSessions(
      [
        { id: "today", updatedAt: "2026-01-15T09:00:00" },
        { id: "older", updatedAt: "2025-06-01T09:00:00" },
      ],
      t,
    );
    expect(groups.map((g) => g.key)).toEqual(["today", "older"]);
  });

  it("falls back to createdAt when updatedAt is missing", () => {
    const groups = groupSessions(
      [{ id: "a", updatedAt: null, createdAt: "2026-01-14T09:00:00" }],
      t,
    );
    expect(groups[0].key).toBe("week");
  });

  it("returns an empty list for no sessions", () => {
    expect(groupSessions([], t)).toEqual([]);
  });

  it("labels groups via the translation function", () => {
    const seen: string[] = [];
    const trackingT = (key: string, fallback: string) => {
      seen.push(key);
      return fallback;
    };
    groupSessions([{ id: "a", updatedAt: "2026-01-15T09:00:00" }], trackingT);
    expect(seen).toContain("chat.group.today");
  });
});
