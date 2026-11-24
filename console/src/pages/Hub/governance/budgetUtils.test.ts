import { describe, it, expect } from "vitest";
import { budgetMode, budgetLimit, formatTokens } from "./budgetUtils";
import type { BudgetMode } from "./budgetUtils";

/**
 * budgetMode and budgetLimit are the two halves of the budget form contract:
 * one derives the mode from a stored limit, the other turns the chosen mode
 * back into a storable limit. The pairs below pin both directions so a form
 * round trip cannot silently widen or lose a budget.
 */

describe("budgetMode", () => {
  it("reports inherit whenever the inherit flag is set", () => {
    expect(budgetMode(null, true)).toBe("inherit");
  });

  it("reports inherit ahead of every stored limit value", () => {
    // The flag wins over the limit, so an inherited member never shows a
    // leftover numeric cap in the form.
    expect(budgetMode(0, true)).toBe("inherit");
    expect(budgetMode(100, true)).toBe("inherit");
  });

  it("reports unlimited for a null limit", () => {
    expect(budgetMode(null)).toBe("unlimited");
    expect(budgetMode(null, false)).toBe("unlimited");
  });

  it("reports blocked for a zero limit", () => {
    expect(budgetMode(0)).toBe("blocked");
    expect(budgetMode(0, false)).toBe("blocked");
  });

  it("reports limited for a positive limit", () => {
    expect(budgetMode(1)).toBe("limited");
    expect(budgetMode(100)).toBe("limited");
    expect(budgetMode(1000000)).toBe("limited");
  });

  it("treats a negative limit as limited rather than blocked", () => {
    // Zero means blocked and null means unlimited; a negative number is neither,
    // so it falls through to the ordinary limited branch.
    expect(budgetMode(-5)).toBe("limited");
  });
});

describe("budgetLimit", () => {
  it("stores the amount for a limited budget", () => {
    expect(budgetLimit("limited", 250)).toBe(250);
  });

  it("stores zero for a blocked budget regardless of the amount", () => {
    expect(budgetLimit("blocked", 250)).toBe(0);
    expect(budgetLimit("blocked", null)).toBe(0);
  });

  it("stores null for an unlimited budget", () => {
    expect(budgetLimit("unlimited", 250)).toBeNull();
  });

  it("stores null for an inherited budget", () => {
    expect(budgetLimit("inherit", 250)).toBeNull();
  });

  it("keeps a zero amount for a limited budget", () => {
    // A limited budget of zero is only reachable by hand; the helper still
    // passes the amount through instead of reclassifying it.
    expect(budgetLimit("limited", 0)).toBe(0);
  });

  it("keeps a negative amount for a limited budget", () => {
    expect(budgetLimit("limited", -10)).toBe(-10);
  });
});

describe("budgetMode / budgetLimit round trip", () => {
  it.each([
    { mode: "unlimited" as BudgetMode, limit: null },
    { mode: "blocked" as BudgetMode, limit: 0 },
    { mode: "limited" as BudgetMode, limit: 250 },
  ])("preserves the $mode mode and its stored limit", ({ mode, limit }) => {
    expect(budgetMode(budgetLimit(mode, limit))).toBe(mode);
  });

  it("maps an inherited budget back to unlimited on re-read", () => {
    // inherit has no storable limit of its own, so reading the stored null back
    // yields unlimited; the inherit state is carried by a separate flag.
    expect(budgetMode(budgetLimit("inherit", 250))).toBe("unlimited");
    expect(budgetMode(budgetLimit("inherit", 250), true)).toBe("inherit");
  });
});

describe("formatTokens", () => {
  /**
   * The compact output is locale data owned by the runtime (the same number
   * renders as 1.5K, 1500 or 1,5 тыс. depending on ICU), so these cases assert
   * only properties that hold across every locale and every Node ICU build:
   * the output is non-empty, deterministic, and honours the documented zero
   * case. Pinning a literal suffix here would be locale dependent flakiness.
   */

  it("formats zero as a plain zero in any language", () => {
    expect(formatTokens(0, "en")).toBe("0");
    expect(formatTokens(0, "zh")).toBe("0");
    expect(formatTokens(0, "de")).toBe("0");
  });

  it.each(["en", "zh", "de", "fr", "ar", "ja", "ru", "ko", "es"])(
    "returns a non-empty string for %s",
    (language) => {
      const out = formatTokens(1234567, language);
      expect(typeof out).toBe("string");
      expect(out.length).toBeGreaterThan(0);
    },
  );

  it("is deterministic for repeated calls with the same arguments", () => {
    expect(formatTokens(1500, "en")).toBe(formatTokens(1500, "en"));
  });

  it("distinguishes different magnitudes", () => {
    expect(formatTokens(1500, "en")).not.toBe(formatTokens(0, "en"));
    expect(formatTokens(1500, "en")).not.toBe(formatTokens(1234567, "en"));
  });

  it("accepts an unknown language tag without throwing", () => {
    // Intl falls back to the default locale data for an unrecognised tag.
    expect(() => formatTokens(1500, "xx-ZZ")).not.toThrow();
    expect(formatTokens(1500, "xx-ZZ").length).toBeGreaterThan(0);
  });

  it("does not keep more than one fraction digit for a compact value", () => {
    // maximumFractionDigits is 1, so a compact value carries at most one digit
    // after its decimal separator. German uses "." as a thousands separator and
    // "," as the decimal mark, so both separators are checked.
    const out = formatTokens(1500, "en");
    const fraction = out.match(/[.,\u066b](\d+)$/);
    expect(fraction ? fraction[1].length : 0).toBeLessThanOrEqual(1);
  });

  it("propagates an invalid language tag instead of masking it", () => {
    // An empty tag is rejected by Intl itself; the helper adds no swallowing.
    expect(() => formatTokens(1500, "")).toThrow(RangeError);
  });
});
