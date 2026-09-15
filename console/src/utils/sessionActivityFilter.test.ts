import { describe, expect, it } from "vitest";

import { filterSessionsByActivity } from "./sessionActivityFilter";

const DAY_MS = 86_400_000;

function session(id: string, daysAgo: number) {
  return {
    id,
    updatedAt: new Date(Date.now() - daysAgo * DAY_MS).toISOString(),
  };
}

describe("filterSessionsByActivity", () => {
  const sessions = [
    session("today", 0),
    session("three", 3),
    session("twenty", 20),
    session("old", 40),
  ];

  it("keeps everything for all", () => {
    expect(filterSessionsByActivity(sessions, "all")).toHaveLength(4);
  });

  it("keeps calendar-today sessions for today", () => {
    expect(
      filterSessionsByActivity(sessions, "today").map((s) => s.id),
    ).toEqual(["today"]);
  });

  it("keeps sessions within 7 days for week", () => {
    expect(filterSessionsByActivity(sessions, "week").map((s) => s.id)).toEqual(
      ["today", "three"],
    );
  });

  it("keeps sessions within 30 days for month", () => {
    expect(
      filterSessionsByActivity(sessions, "month").map((s) => s.id),
    ).toEqual(["today", "three", "twenty"]);
  });

  it("falls back to createdAt when updatedAt is missing", () => {
    const created = [{ id: "c", createdAt: new Date().toISOString() }];
    expect(filterSessionsByActivity(created, "today")).toHaveLength(1);
  });

  it("treats missing timestamps as older", () => {
    const undated = [{ id: "u" }];
    expect(filterSessionsByActivity(undated, "month")).toHaveLength(0);
    expect(filterSessionsByActivity(undated, "all")).toHaveLength(1);
  });
});
