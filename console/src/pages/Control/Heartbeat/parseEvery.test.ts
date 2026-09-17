import { describe, it, expect } from "vitest";
import { parseEvery, serializeEvery } from "./parseEvery";

describe("parseEvery", () => {
  it("empty string defaults to 6h", () => {
    expect(parseEvery("")).toEqual({ number: 6, unit: "h" });
  });

  it("pure hours: 6h → { number: 6, unit: 'h' }", () => {
    expect(parseEvery("6h")).toEqual({ number: 6, unit: "h" });
  });

  it("pure minutes: 30m → { number: 30, unit: 'm' }", () => {
    expect(parseEvery("30m")).toEqual({ number: 30, unit: "m" });
  });

  it("mixed 2h30m → total minutes 150 (not divisible by 60)", () => {
    expect(parseEvery("2h30m")).toEqual({ number: 150, unit: "m" });
  });
});

describe("serializeEvery", () => {
  it("serializes hours and minutes correctly", () => {
    expect(serializeEvery({ number: 6, unit: "h" })).toBe("6h");
    expect(serializeEvery({ number: 30, unit: "m" })).toBe("30m");
  });
});
