import { describe, it, expect } from "vitest";
import { DEFAULT_FORM_VALUES } from "./constants";

describe("DEFAULT_FORM_VALUES", () => {
  it("has all required top-level keys", () => {
    const keys = [
      "enabled",
      "save_result_to_inbox",
      "scheduleType",
      "schedule",
      "onceRunAt",
      "cronType",
      "task_type",
      "request",
      "dispatch",
      "runtime",
    ];
    for (const key of keys) {
      expect(DEFAULT_FORM_VALUES).toHaveProperty(key);
    }
  });

  it("default schedule.type is 'cron' and schedule.cron is '0 9 * * *'", () => {
    expect(DEFAULT_FORM_VALUES.schedule.type).toBe("cron");
    expect(DEFAULT_FORM_VALUES.schedule.cron).toBe("0 9 * * *");
  });
});
