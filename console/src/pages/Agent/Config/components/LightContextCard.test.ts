import { describe, expect, it } from "vitest";

import { usesTieredToolResultSettings } from "./toolResultSettings";

describe("usesTieredToolResultSettings", () => {
  it("hides old-preview tiers for Scroll", () => {
    expect(usesTieredToolResultSettings("scroll")).toBe(false);
    expect(usesTieredToolResultSettings(undefined)).toBe(false);
  });

  it("shows old-preview tiers for Native context", () => {
    expect(usesTieredToolResultSettings("native")).toBe(true);
  });
});
