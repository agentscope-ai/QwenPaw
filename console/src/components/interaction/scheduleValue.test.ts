import { describe, expect, it } from "vitest";
import { readSchedule, writeSchedule } from "./scheduleValue";

describe("memory schedule representation", () => {
  it("round trips daily and named weekday schedules", () => {
    expect(readSchedule("30 23 * * *")).toEqual({ minutes: 1410, days: [] });
    expect(writeSchedule(1410, [])).toBe("30 23 * * *");
    expect(writeSchedule(570, ["fri", "mon"])).toBe("30 9 * * mon,fri");
    expect(readSchedule("30 9 * * mon,fri")).toEqual({
      minutes: 570,
      days: ["mon", "fri"],
    });
  });
  it("leaves complex and numeric-weekday schedules in advanced mode without reinterpreting them", () => {
    for (const value of [
      "0 9 * * 0",
      "*/15 * * * *",
      "0 9 * * mon-fri",
      "0 9 1 * *",
      "60 9 * * *",
      "0 24 * * *",
    ])
      expect(readSchedule(value)).toBeNull();
  });
});
