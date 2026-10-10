import { describe, expect, it } from "vitest";
import { cacheHitRate, formatPercent } from "./cacheUsage";

describe("cache usage helpers", () => {
  it("calculates a token-weighted hit rate", () => {
    expect(cacheHitRate(80, 100)).toBe(80);
  });

  it("returns no rate when the provider has no eligible input", () => {
    expect(cacheHitRate(0, 0)).toBeNull();
  });

  it("formats cold misses and unavailable data distinctly", () => {
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(null)).toBe("—");
  });

  it("does not display a partial cache hit as 100 percent", () => {
    expect(formatPercent(99.5)).toBe("99.5%");
    expect(formatPercent(99.95)).toBe("99.95%");
    expect(formatPercent(100)).toBe("100%");
  });
});
