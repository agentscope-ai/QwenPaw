import { describe, expect, it } from "vitest";

import { calculateReserveThreshold } from "./toolResultSettings";

describe("calculateReserveThreshold", () => {
  it("applies Scroll's bounded recent-tail budget", () => {
    expect(calculateReserveThreshold(128_000, 0.1)).toBe(12_800);
    expect(calculateReserveThreshold(1_000_000, 0.1)).toBe(40_000);
    expect(calculateReserveThreshold(32_000, 0.01)).toBe(3_200);
  });
});
