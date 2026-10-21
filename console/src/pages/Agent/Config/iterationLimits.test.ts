import { describe, expect, it } from "vitest";
import {
  ITERATION_LIMIT_MAX,
  ITERATION_LIMIT_MIN,
  normalizeIterationLimit,
} from "./iterationLimits";

describe("normalizeIterationLimit", () => {
  it("keeps a limit inside the schema bounds", () => {
    expect(normalizeIterationLimit(ITERATION_LIMIT_MIN)).toBe(
      ITERATION_LIMIT_MIN,
    );
    expect(normalizeIterationLimit(30)).toBe(30);
    expect(normalizeIterationLimit(ITERATION_LIMIT_MAX)).toBe(
      ITERATION_LIMIT_MAX,
    );
  });

  it("rejects values the schema would refuse", () => {
    expect(normalizeIterationLimit(0)).toBeNull();
    expect(normalizeIterationLimit(9999)).toBeNull();
    expect(normalizeIterationLimit(ITERATION_LIMIT_MAX + 1)).toBeNull();
    expect(normalizeIterationLimit(12.5)).toBeNull();
    expect(normalizeIterationLimit(Number.NaN)).toBeNull();
  });

  it("rejects unset and non-numeric values", () => {
    expect(normalizeIterationLimit(null)).toBeNull();
    expect(normalizeIterationLimit(undefined)).toBeNull();
    expect(normalizeIterationLimit("30")).toBeNull();
  });
});
