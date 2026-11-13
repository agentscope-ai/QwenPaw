import { describe, expect, it } from "vitest";

import { formatCompact } from "./formatNumber";

describe("formatCompact", () => {
  it("formats values below 1000 with locale grouping and no suffix", () => {
    expect(formatCompact(0)).toBe("0");
    expect(formatCompact(999)).toBe("999");
  });

  it("formats K/M/B bands", () => {
    expect(formatCompact(1000)).toBe("1K");
    expect(formatCompact(1500)).toBe("1.5K");
    expect(formatCompact(1_200_000)).toBe("1.2M");
    expect(formatCompact(1_000_000_000)).toBe("1B");
  });

  it("promotes to the next unit when rounding carries to 1000", () => {
    // 999_999 / 1e3 = 999.999 -> toFixed(1) rounds to "1000.0"; must render "1M".
    expect(formatCompact(999_999)).toBe("1M");
    expect(formatCompact(999_950)).toBe("1M");
    expect(formatCompact(999_999_999)).toBe("1B");
    expect(formatCompact(999_950_000)).toBe("1B");
  });

  it("does not promote just below the rounding boundary", () => {
    expect(formatCompact(999_499)).toBe("999.5K");
    expect(formatCompact(999_499_999)).toBe("999.5M");
  });

  it("returns 0 for non-finite or negative input", () => {
    expect(formatCompact(Number.NaN)).toBe("0");
    expect(formatCompact(-5)).toBe("0");
  });
});
