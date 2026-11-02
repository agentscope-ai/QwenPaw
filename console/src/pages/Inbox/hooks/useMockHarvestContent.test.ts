/**
 * Tests for generateMockHistory (useMockHarvestContent.ts).
 *
 * The helper builds the eight demo magazine entries that the inbox history
 * viewer paginates through. It derives every date from `new Date()`, so the
 * clock is pinned with fake timers; without that the date assertions would
 * drift with the real time of day and turn flaky.
 *
 * Covers:
 * - always exactly eight entries (the viewer's page count is hard-wired to it)
 * - id / title derivation from the harvest name, including the 1-based numbering
 * - the day offset walk: first entry is seven days old, last entry is today
 * - dates are strictly ascending by index (the timeline renders oldest first)
 * - content is the shared placeholder copy, identical across entries
 * - names that carry spaces, CJK text or emoji round-trip into id and title
 *   verbatim (the viewer uses the id as a React key)
 */
// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { generateMockHistory } from "./useMockHarvestContent";

// Pinned baseline so `setDate(getDate() - daysAgo)` is deterministic.
const BASELINE = new Date("2026-03-10T12:00:00.000Z");

const DAY_MS = 24 * 60 * 60 * 1000;

describe("generateMockHistory", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASELINE);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns exactly eight entries", () => {
    expect(generateMockHistory("daily")).toHaveLength(8);
  });

  it("derives the id from the harvest name and the zero-based index", () => {
    const items = generateMockHistory("daily");

    expect(items[0].id).toBe("daily-0");
    expect(items[7].id).toBe("daily-7");
  });

  it("numbers the title from one while the id stays zero-based", () => {
    const items = generateMockHistory("daily");

    expect(items[0].title).toBe("daily \u00b7 #1");
    expect(items[3].title).toBe("daily \u00b7 #4");
    expect(items[7].title).toBe("daily \u00b7 #8");
  });

  it("gives every entry a unique id so the viewer's React keys never collide", () => {
    const ids = generateMockHistory("daily").map((m) => m.id);

    expect(new Set(ids).size).toBe(ids.length);
  });

  it("dates the first entry seven days back and the last entry today", () => {
    const items = generateMockHistory("daily");

    expect(items[0].date.getTime()).toBe(BASELINE.getTime() - 7 * DAY_MS);
    expect(items[7].date.getTime()).toBe(BASELINE.getTime());
  });

  it("walks the day offset down by one per entry", () => {
    const items = generateMockHistory("daily");

    const offsets = items.map((m) =>
      Math.round((BASELINE.getTime() - m.date.getTime()) / DAY_MS),
    );
    expect(offsets).toEqual([7, 6, 5, 4, 3, 2, 1, 0]);
  });

  it("keeps dates strictly ascending so the timeline reads oldest to newest", () => {
    const items = generateMockHistory("daily");

    for (let i = 1; i < items.length; i += 1) {
      expect(items[i].date.getTime()).toBeGreaterThan(
        items[i - 1].date.getTime(),
      );
    }
  });

  it("repeats the same placeholder copy across all entries", () => {
    const items = generateMockHistory("daily");
    const copies = new Set(items.map((m) => m.content));

    expect(copies.size).toBe(1);
    const [only] = [...copies];
    expect(only).toContain("mock harvest content card");
    expect(only).not.toBe("");
  });

  it("keeps a name with spaces verbatim in both id and title", () => {
    const items = generateMockHistory("weekly digest");

    expect(items[0].id).toBe("weekly digest-0");
    expect(items[0].title).toBe("weekly digest \u00b7 #1");
  });

  it("keeps CJK and emoji names verbatim in both id and title", () => {
    const items = generateMockHistory("\u65e9\u62a5 \ud83d\udcf0");

    expect(items[0].id).toBe("\u65e9\u62a5 \ud83d\udcf0-0");
    expect(items[0].title).toBe("\u65e9\u62a5 \ud83d\udcf0 \u00b7 #1");
    expect(items[0].id).toContain("\ud83d\udcf0");
  });

  it("tolerates an empty name without throwing or changing the count", () => {
    const items = generateMockHistory("");

    expect(items).toHaveLength(8);
    expect(items[0].id).toBe("-0");
    expect(items[0].title).toBe(" \u00b7 #1");
  });

  it("recomputes dates against the pinned clock rather than a stale one", () => {
    const first = generateMockHistory("daily");

    vi.setSystemTime(new Date("2026-03-11T12:00:00.000Z"));
    const second = generateMockHistory("daily");

    expect(second[7].date.getTime() - first[7].date.getTime()).toBe(DAY_MS);
    expect(second.map((m) => m.id)).toEqual(first.map((m) => m.id));
  });
});
