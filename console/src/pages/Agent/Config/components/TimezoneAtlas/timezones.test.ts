import { describe, expect, it } from "vitest";
import {
  fixedTimezone,
  timezoneOffset,
  offsetLabel,
  timezoneName,
} from "./timezones";

describe("UTC map selection", () => {
  it.each([-12, -5, 0, 8, 12, 14])(
    "stores UTC%+i with the correct IANA sign",
    (hours) => {
      const zone = fixedTimezone(hours * 60);
      expect(timezoneOffset(zone, new Date("2026-01-15T12:00:00Z"))).toBe(
        hours * 60,
      );
      expect(timezoneOffset(zone, new Date("2026-07-15T12:00:00Z"))).toBe(
        hours * 60,
      );
    },
  );
  it("retains fractional regional offsets", () => {
    const date = new Date("2026-01-15T12:00:00Z");
    expect(offsetLabel(timezoneOffset("Asia/Kathmandu", date))).toBe(
      "UTC+05:45",
    );
    expect(offsetLabel(timezoneOffset("Asia/Kolkata", date))).toBe("UTC+05:30");
  });
  it("distinguishes a regional DST zone from a fixed UTC offset", () => {
    expect(
      timezoneOffset("America/New_York", new Date("2026-01-15T12:00:00Z")),
    ).toBe(-300);
    expect(
      timezoneOffset("America/New_York", new Date("2026-07-15T12:00:00Z")),
    ).toBe(-240);
  });
});

it("displays Beijing for the standard China identifier and localizes other zones", () => {
  expect(timezoneName("Asia/Shanghai", "zh", "北京时间")).toBe("北京时间");
  expect(timezoneName("Asia/Shanghai", "en", "Beijing time")).toBe(
    "Beijing time",
  );
  expect(timezoneName("Etc/GMT-8", "zh", "北京时间")).toBe("UTC+08:00");
  expect(timezoneName("Europe/Paris", "en", "Beijing time")).not.toBe(
    "Europe/Paris",
  );
});
