/**
 * normalizeLevel maps raw tool-execution-level strings to the four
 * canonical levels, falling back to "AUTO" for anything unrecognized.
 * This guards settings round-trips (missing/corrupted values must never
 * crash the approval UI or lock users out of tool execution).
 */
import { describe, it, expect } from "vitest";
import { LEVELS, normalizeLevel } from "./approval";

describe("LEVELS", () => {
  it("exposes the four levels in strictness order", () => {
    expect(LEVELS).toEqual(["STRICT", "SMART", "AUTO", "OFF"]);
  });
});

describe("normalizeLevel", () => {
  it.each(["STRICT", "SMART", "AUTO", "OFF"])(
    "passes through the valid level %s",
    (level) => {
      expect(normalizeLevel(level)).toBe(level);
    },
  );

  it("accepts lowercase input", () => {
    expect(normalizeLevel("strict")).toBe("STRICT");
  });

  it("accepts mixed-case input", () => {
    expect(normalizeLevel("Smart")).toBe("SMART");
  });

  it("falls back to AUTO for an unrecognized level", () => {
    expect(normalizeLevel("yolo")).toBe("AUTO");
  });

  it("falls back to AUTO for an empty string", () => {
    expect(normalizeLevel("")).toBe("AUTO");
  });

  it("falls back to AUTO for undefined (missing settings)", () => {
    expect(normalizeLevel(undefined)).toBe("AUTO");
  });
});
