import { describe, it, expect } from "vitest";
import { parseCron, serializeCron } from "./parseCron";

describe("parseCron", () => {
  it("empty string defaults to daily at 09:00", () => {
    expect(parseCron("")).toEqual({ type: "daily", hour: 9, minute: 0 });
  });

  it('"0 * * * *" parses as hourly', () => {
    expect(parseCron("0 * * * *")).toEqual({ type: "hourly", minute: 0 });
  });

  it('"0 9 * * *" parses as daily at 09:00', () => {
    expect(parseCron("0 9 * * *")).toEqual({
      type: "daily",
      hour: 9,
      minute: 0,
    });
  });

  it('"30 14 * * *" parses as daily at 14:30', () => {
    expect(parseCron("30 14 * * *")).toEqual({
      type: "daily",
      hour: 14,
      minute: 30,
    });
  });

  it('"0 9 * * mon,wed,fri" parses as weekly with named days', () => {
    expect(parseCron("0 9 * * mon,wed,fri")).toEqual({
      type: "weekly",
      hour: 9,
      minute: 0,
      daysOfWeek: ["mon", "wed", "fri"],
    });
  });

  it('"*/15 * * * *" parses as custom with rawCron preserved', () => {
    expect(parseCron("*/15 * * * *")).toEqual({
      type: "custom",
      rawCron: "*/15 * * * *",
    });
  });

  it('"0 9 * * 1,3,5" converts numeric days to named abbreviations', () => {
    const result = parseCron("0 9 * * 1,3,5");
    expect(result.type).toBe("weekly");
    expect(result.daysOfWeek).toEqual(["mon", "wed", "fri"]);
  });
});

describe("serializeCron", () => {
  it("hourly type serializes to '0 * * * *'", () => {
    expect(serializeCron({ type: "hourly" })).toBe("0 * * * *");
  });

  it("daily type with hour and minute serializes correctly", () => {
    expect(serializeCron({ type: "daily", hour: 9, minute: 30 })).toBe(
      "30 9 * * *",
    );
  });

  it("custom type preserves rawCron verbatim", () => {
    expect(serializeCron({ type: "custom", rawCron: "*/15 * * * *" })).toBe(
      "*/15 * * * *",
    );
  });
});
