import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useDataAggregation } from "./useDataAggregation";
import type { TokenUsageRecord } from "../../../../api/types/tokenUsage";

function record(overrides: Partial<TokenUsageRecord> = {}): TokenUsageRecord {
  return {
    date: "2026-07-23",
    provider_id: "openai",
    model: "gpt-4",
    user_id: "alice",
    prompt_tokens: 100,
    completion_tokens: 50,
    call_count: 1,
    ...overrides,
  };
}

describe("useDataAggregation", () => {
  it("aggregates per user across models and dates", () => {
    const { result } = renderHook(() =>
      useDataAggregation([
        record(),
        record({ date: "2026-07-24", prompt_tokens: 10 }),
        record({ user_id: "bob", prompt_tokens: 20, completion_tokens: 5 }),
      ]),
    );

    expect(result.current?.by_user.alice).toEqual({
      prompt_tokens: 110,
      completion_tokens: 100,
      call_count: 2,
    });
    expect(result.current?.by_user.bob.prompt_tokens).toBe(20);
  });

  it("keeps model and date totals independent of the user split", () => {
    const { result } = renderHook(() =>
      useDataAggregation([record(), record({ user_id: "bob" })]),
    );

    expect(result.current?.by_model["openai:gpt-4"].prompt_tokens).toBe(200);
    expect(result.current?.by_date["2026-07-23"].call_count).toBe(2);
    expect(result.current?.total_prompt_tokens).toBe(200);
  });
});
