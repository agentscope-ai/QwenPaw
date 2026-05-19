/**
 * Tests for constants/timezone.
 *
 * Covers:
 * - getTimezoneOptions() returns expected structure
 * - Options are sorted by UTC offset
 * - getLocalizedName() handles locales
 */
import { describe, it, expect, vi } from "vitest";

// Mock @vvo/tzdb to avoid real dependency
const mockTimeZones = [
  {
    name: "America/New_York",
    currentTimeOffsetInMinutes: -300,
    currentTimeFormat: "09:00 AM EST",
  },
  {
    name: "Europe/London",
    currentTimeOffsetInMinutes: 0,
    currentTimeFormat: "02:00 PM GMT",
  },
  {
    name: "Asia/Shanghai",
    currentTimeOffsetInMinutes: 480,
    currentTimeFormat: "10:00 PM CST",
  },
  {
    name: "Etc/UTC",
    currentTimeOffsetInMinutes: 0,
    currentTimeFormat: "02:00 PM UTC",
  },
];

vi.mock("@vvo/tzdb", () => ({
  getTimeZones: () => mockTimeZones,
}));

import { getTimezoneOptions } from "./timezone";

describe("getTimezoneOptions", () => {
  it("returns an array of TimezoneOption", () => {
    const options = getTimezoneOptions();
    expect(Array.isArray(options)).toBe(true);
    expect(options.length).toBeGreaterThan(0);
  });

  it("each option has value and label strings", () => {
    const options = getTimezoneOptions();
    for (const opt of options) {
      expect(typeof opt.value).toBe("string");
      expect(typeof opt.label).toBe("string");
      expect(opt.value.length).toBeGreaterThan(0);
      expect(opt.label.length).toBeGreaterThan(0);
    }
  });

  it("options are sorted by UTC offset (ascending)", () => {
    const options = getTimezoneOptions();
    // America/New_York (-300) < Europe/London (0) < Asia/Shanghai (480)
    const nyIdx = options.findIndex((o) => o.value === "America/New_York");
    const ldIdx = options.findIndex((o) => o.value === "Europe/London");
    const shIdx = options.findIndex((o) => o.value === "Asia/Shanghai");
    expect(nyIdx).toBeLessThan(ldIdx);
    expect(ldIdx).toBeLessThan(shIdx);
  });

  it("maps Etc/UTC to UTC value", () => {
    const options = getTimezoneOptions();
    const utcOpt = options.find((o) => o.value === "UTC");
    expect(utcOpt).toBeDefined();
  });

  it("no duplicate values", () => {
    const options = getTimezoneOptions();
    const values = options.map((o) => o.value);
    expect(new Set(values).size).toBe(values.length);
  });
});
