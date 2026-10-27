import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { cacheHitRate } from "../../../../utils/cacheUsage";
import { useDataAggregation } from "./useDataAggregation";

describe("useDataAggregation cache usage", () => {
  it("aggregates cache tokens before calculating the hit rate", () => {
    const { result } = renderHook(() =>
      useDataAggregation([
        {
          date: "2026-08-27",
          provider_id: "deepseek",
          model: "deepseek-chat",
          prompt_tokens: 100,
          completion_tokens: 10,
          cache_read_tokens: 90,
          cache_write_tokens: 0,
          cache_eligible_input_tokens: 100,
          cache_observed_calls: 1,
          call_count: 1,
        },
        {
          date: "2026-08-27",
          provider_id: "deepseek",
          model: "deepseek-chat",
          prompt_tokens: 900,
          completion_tokens: 20,
          cache_read_tokens: 450,
          cache_write_tokens: 0,
          cache_eligible_input_tokens: 900,
          cache_observed_calls: 1,
          call_count: 1,
        },
      ]),
    );

    expect(result.current?.total_cache_read_tokens).toBe(540);
    expect(result.current?.total_cache_eligible_input_tokens).toBe(1000);
    expect(
      cacheHitRate(
        result.current?.total_cache_read_tokens || 0,
        result.current?.total_cache_eligible_input_tokens || 0,
      ),
    ).toBe(54);
  });
});
