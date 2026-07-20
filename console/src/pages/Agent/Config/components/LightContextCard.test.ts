import { describe, expect, it } from "vitest";

import {
  calculateReserveThreshold,
  usesTieredToolResultSettings,
} from "./toolResultSettings";

describe("usesTieredToolResultSettings", () => {
  it("hides old-preview tiers for Scroll", () => {
    expect(usesTieredToolResultSettings("scroll")).toBe(false);
    expect(usesTieredToolResultSettings(undefined)).toBe(false);
  });

  it("shows old-preview tiers for Native context", () => {
    expect(usesTieredToolResultSettings("native")).toBe(true);
  });
});

describe("calculateReserveThreshold", () => {
  it("applies Scroll's bounded recent-tail budget", () => {
    expect(calculateReserveThreshold(128_000, 0.1, "scroll")).toBe(12_800);
    expect(calculateReserveThreshold(1_000_000, 0.1, "scroll")).toBe(40_000);
    expect(calculateReserveThreshold(32_000, 0.01, "scroll")).toBe(3_200);
  });

  it("uses the configured ratio directly for Native context", () => {
    expect(calculateReserveThreshold(1_000_000, 0.1, "native")).toBe(100_000);
  });
});
