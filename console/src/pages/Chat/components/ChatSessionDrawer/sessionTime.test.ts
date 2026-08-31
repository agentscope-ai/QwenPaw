import { describe, expect, it } from "vitest";
import { formatSessionTime, pickSessionDisplayTime } from "./sessionTime";

// ---------------------------------------------------------------------------
// pickSessionDisplayTime — regression for #769
// (the drawer showed the creation time where the update time belongs, so a
// session that had just been active still looked stale; display must prefer
// the update timestamp and only fall back to creation when never updated)
// ---------------------------------------------------------------------------
describe("pickSessionDisplayTime (#769)", () => {
  const CREATED = "2026-08-01T10:00:00Z";
  const UPDATED = "2026-08-23T12:34:56Z";

  it("prefers updatedAt when both are present", () => {
    expect(
      pickSessionDisplayTime({ createdAt: CREATED, updatedAt: UPDATED }),
    ).toBe(UPDATED);
  });

  it("falls back to createdAt when the session was never updated", () => {
    expect(
      pickSessionDisplayTime({ createdAt: CREATED, updatedAt: null }),
    ).toBe(CREATED);
    expect(pickSessionDisplayTime({ createdAt: CREATED })).toBe(CREATED);
  });

  it("returns null when no timestamps exist", () => {
    expect(pickSessionDisplayTime({})).toBeNull();
    expect(
      pickSessionDisplayTime({ createdAt: null, updatedAt: null }),
    ).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// formatSessionTime — stable local rendering contract
// ---------------------------------------------------------------------------
describe("formatSessionTime (#769)", () => {
  it("formats as local YYYY-MM-DD HH:mm:ss", () => {
    // Build a local date explicitly so the assertion is timezone-independent.
    const d = new Date(2026, 7, 23, 12, 34, 56);
    expect(formatSessionTime(d.toISOString())).toBe("2026-08-23 12:34:56");
  });

  it("pads single-digit fields", () => {
    const d = new Date(2026, 0, 5, 3, 2, 1);
    expect(formatSessionTime(d.toISOString())).toBe("2026-01-05 03:02:01");
  });

  it("returns empty string for missing or unparseable input", () => {
    expect(formatSessionTime(null)).toBe("");
    expect(formatSessionTime(undefined)).toBe("");
    expect(formatSessionTime("")).toBe("");
    expect(formatSessionTime("not-a-date")).toBe("");
  });
});
