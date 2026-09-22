import { describe, expect, it } from "vitest";
import { formatTime } from "./constants";

// formatTime renders through Date#toLocaleString("zh-CN", ...), so its exact
// text depends on the host locale and timezone. Every assertion below compares
// two calls made in the SAME process, which makes them locale- and
// timezone-independent while still pinning the normalisation behaviour.

describe("formatTime - absent input", () => {
  it("renders N/A for null", () => {
    expect(formatTime(null)).toBe("N/A");
  });

  it("renders N/A for undefined", () => {
    // The signature says `string | number | null`, but the guard also covers
    // undefined; callers can still pass a missing field.
    expect(formatTime(undefined as unknown as null)).toBe("N/A");
  });
});

describe("formatTime - numeric timestamps are used as-is", () => {
  it("formats the epoch without any timezone normalisation", () => {
    // A number skips normalizeTimestamp entirely, so it must equal what
    // toLocaleString gives for that exact instant.
    expect(formatTime(0)).toBe(
      new Date(0).toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
  });

  it("treats 0 as a real timestamp rather than a missing value", () => {
    expect(formatTime(0)).not.toBe("N/A");
  });

  it("formats a millisecond epoch value", () => {
    const ms = Date.parse("2026-09-17T02:41:56.000Z");
    expect(formatTime(ms)).toBe(
      new Date(ms).toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
  });
});

describe("formatTime - timezone normalisation (the bug this helper exists for)", () => {
  it("treats a naive timestamp as UTC, same as one carrying a Z suffix", () => {
    // datetime.utcnow() emits no timezone suffix; without appending "Z" the
    // browser would read it as LOCAL time and display the wrong instant.
    expect(formatTime("2026-09-17T02:41:56")).toBe(
      formatTime("2026-09-17T02:41:56Z"),
    );
  });

  it("leaves an explicit Z suffix untouched", () => {
    expect(formatTime("2026-09-17T02:41:56Z")).toBe(
      new Date("2026-09-17T02:41:56Z").toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
  });

  it("leaves an explicit +HH:MM offset untouched", () => {
    // [Z+\-]\d{2}:?\d{2}$ matches "+08:00", so no Z is appended.
    expect(formatTime("2026-09-17T10:41:56+08:00")).toBe(
      formatTime("2026-09-17T02:41:56Z"),
    );
  });

  it("leaves an explicit -HH:MM offset untouched", () => {
    expect(formatTime("2026-09-16T22:41:56-04:00")).toBe(
      formatTime("2026-09-17T02:41:56Z"),
    );
  });

  it("recognises an offset written without the colon", () => {
    // The regex allows \d{2}:?\d{2}, so "+0800" is already timezone-aware and
    // must NOT get a Z appended (that would corrupt the value).
    expect(formatTime("2026-09-17T10:41:56+0800")).toBe(
      formatTime("2026-09-17T02:41:56Z"),
    );
  });

  it("appends Z to a naive date-time that carries fractional seconds", () => {
    expect(formatTime("2026-09-17T02:41:56.789")).toBe(
      formatTime("2026-09-17T02:41:56.789Z"),
    );
  });

  it("appends Z to a naive date-only value", () => {
    expect(formatTime("2026-09-17")).toBe(formatTime("2026-09-17Z"));
  });

  it("does not double-append when the value already ends in Z", () => {
    // A double suffix would produce an Invalid Date; equality with the plain
    // Date parse proves only one Z is in effect.
    expect(formatTime("2026-09-17T02:41:56Z")).not.toBe("Invalid Date");
  });

  it("trims nothing, so surrounding whitespace makes the value invalid", () => {
    // Pinned as-is: normalizeTimestamp does not trim, and "Z" is appended to
    // the raw string, which Date then rejects. Whether it SHOULD trim is a
    // product decision, not a test decision.
    expect(formatTime(" 2026-09-17T02:41:56 ")).toBe(
      new Date(" 2026-09-17T02:41:56 Z").toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
  });
});

describe("formatTime - output shape", () => {
  it("renders year, month, day, hour and minute for a known instant", () => {
    const out = formatTime("2026-09-17T02:41:56Z");
    // Locale-independent structural checks: the year is present and the
    // string is not the Invalid Date sentinel.
    expect(out).toContain("2026");
    expect(out).not.toBe("Invalid Date");
    expect(out.length).toBeGreaterThan(0);
  });

  it("returns Invalid Date for an unparseable string", () => {
    expect(formatTime("not a timestamp")).toBe(
      new Date("not a timestampZ").toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    );
  });
});
