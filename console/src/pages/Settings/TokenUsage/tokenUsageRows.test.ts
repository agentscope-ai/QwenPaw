import { describe, expect, it } from "vitest";
import { buildByDateRows } from "./tokenUsageRows";

// ---------------------------------------------------------------------------
// buildByDateRows — regression for #3368
// (the token usage by-date table listed the oldest day first, forcing users
// to scroll to the bottom to see today's numbers; rows must come out in
// date-descending order)
// ---------------------------------------------------------------------------
describe("buildByDateRows (#3368)", () => {
  const stats = (p = 1, c = 2, n = 3) => ({
    prompt_tokens: p,
    completion_tokens: c,
    call_count: n,
  });

  it("returns an empty list for null/undefined/empty input", () => {
    expect(buildByDateRows(null)).toEqual([]);
    expect(buildByDateRows(undefined)).toEqual([]);
    expect(buildByDateRows({})).toEqual([]);
  });

  it("sorts rows by date descending (newest first)", () => {
    const rows = buildByDateRows({
      "2026-01-01": stats(),
      "2026-03-15": stats(),
      "2026-02-10": stats(),
    });

    expect(rows.map((r) => r.date)).toEqual([
      "2026-03-15",
      "2026-02-10",
      "2026-01-01",
    ]);
  });

  it("keeps the newest row first regardless of object key order", () => {
    // Object.entries order follows insertion order; the sort must not rely on
    // the backend happening to return dates in any particular order.
    const rows = buildByDateRows({
      "2025-12-31": stats(),
      "2026-08-23": stats(),
      "2026-01-01": stats(),
    });

    expect(rows[0].date).toBe("2026-08-23");
    expect(rows[rows.length - 1].date).toBe("2025-12-31");
  });

  it("maps every stats field and uses the date as key", () => {
    const rows = buildByDateRows({
      "2026-08-23": {
        prompt_tokens: 10,
        completion_tokens: 20,
        call_count: 5,
      },
    });

    expect(rows).toEqual([
      {
        key: "2026-08-23",
        date: "2026-08-23",
        prompt_tokens: 10,
        completion_tokens: 20,
        call_count: 5,
      },
    ]);
  });

  it("handles a single row (N=1 boundary)", () => {
    const rows = buildByDateRows({ "2026-08-23": stats() });
    expect(rows).toHaveLength(1);
    expect(rows[0].date).toBe("2026-08-23");
  });
});
