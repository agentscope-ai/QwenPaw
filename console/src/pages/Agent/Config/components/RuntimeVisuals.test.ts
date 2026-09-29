import { describe, expect, it } from "vitest";
import { retryDelays } from "./retryTiming";

describe("retry timing preview", () => {
  it("matches capped exponential backoff for the configured retries", () => {
    expect(retryDelays(5, 1.5, 5)).toEqual([1.5, 3, 5, 5, 5]);
  });
  it("shows no retries when disabled and bounds the visible chart", () => {
    expect(retryDelays(0, 1, 10)).toEqual([]);
    expect(retryDelays(100, 1, 10)).toHaveLength(8);
  });
});
