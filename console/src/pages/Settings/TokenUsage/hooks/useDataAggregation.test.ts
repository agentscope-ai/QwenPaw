import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import type { TokenUsageRecord } from "../../../../api/types/tokenUsage";
import {
  UNKNOWN_AGENT_KEY,
  useDataAggregation,
} from "./useDataAggregation";

function makeRecord(
  overrides: Partial<TokenUsageRecord> = {},
): TokenUsageRecord {
  return {
    date: "2026-04-24",
    provider_id: "openai",
    model: "gpt-4",
    prompt_tokens: 10,
    completion_tokens: 5,
    call_count: 1,
    ...overrides,
  };
}

describe("useDataAggregation", () => {
  it("groups missing agent_id under a nonempty unknown key", () => {
    const { result } = renderHook(() =>
      useDataAggregation([
        makeRecord({ agent_id: "" }),
        makeRecord({ agent_id: undefined, prompt_tokens: 3 }),
        makeRecord({ agent_id: "agent-a", prompt_tokens: 7 }),
      ]),
    );

    const byAgent = result.current?.by_agent;
    expect(byAgent).toBeTruthy();
    expect(byAgent?.[UNKNOWN_AGENT_KEY]?.agent_id).toBe("");
    expect(byAgent?.[UNKNOWN_AGENT_KEY]?.prompt_tokens).toBe(13);
    expect(byAgent?.["agent-a"]?.prompt_tokens).toBe(7);
  });
});
