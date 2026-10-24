import { describe, expect, it } from "vitest";
import dayjs from "dayjs";
import type { TokenUsageRecord } from "@/api/types/tokenUsage";
import { buildActivity } from "./usageActivityData";

const record = (date: string, provider_id = "provider"): TokenUsageRecord => ({
  date,
  provider_id,
  model: "model",
  prompt_tokens: 100,
  completion_tokens: 20,
  call_count: 1,
  cache_read_tokens: 50,
  cache_write_tokens: 0,
  cache_eligible_input_tokens: 100,
  cache_observed_calls: 1,
});
describe("token activity calendar", () => {
  it("sums input and output once, keeps providers distinct and excludes other dates", () => {
    const result = buildActivity(
      [
        record("2026-09-01"),
        record("2026-09-01", "other"),
        record("2026-08-31"),
      ],
      dayjs("2026-09-01"),
      dayjs("2026-09-30"),
    );
    expect(result.days.find((day) => day.date === "2026-09-01")?.value).toBe(
      240,
    );
    expect(result.models).toEqual([
      ["provider:model", 120],
      ["other:model", 120],
    ]);
    expect(result.days[0]).toEqual({
      date: "2026-08-31",
      value: 0,
      inRange: false,
    });
    expect(result.days.find((day) => day.date === "2026-09-02")).toEqual({
      date: "2026-09-02",
      value: 0,
      inRange: true,
    });
    expect(result.days.length % 7).toBe(0);
  });
  it("includes leap day across month boundaries with an empty safe scale", () => {
    const result = buildActivity([], dayjs("2024-02-28"), dayjs("2024-03-01"));
    expect(
      result.days.filter((day) => day.inRange).map((day) => day.date),
    ).toEqual(["2024-02-28", "2024-02-29", "2024-03-01"]);
    expect(result.max).toBe(1);
    expect(result.models).toEqual([]);
  });
});
