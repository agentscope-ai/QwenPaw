import { useMemo } from "react";
import type { TokenUsageRecord } from "../../../../api/types/tokenUsage";

interface AggregatedData {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_calls: number;
  by_model: Record<
    string,
    {
      model: string;
      provider_id: string;
      prompt_tokens: number;
      completion_tokens: number;
      call_count: number;
    }
  >;
  by_date: Record<
    string,
    {
      prompt_tokens: number;
      completion_tokens: number;
      call_count: number;
    }
  >;
  by_date_model: Record<
    string,
    Record<
      string,
      {
        model: string;
        provider_id: string;
        prompt_tokens: number;
        completion_tokens: number;
        call_count: number;
      }
    >
  >;
}

export function useDataAggregation(records: TokenUsageRecord[]) {
  return useMemo<AggregatedData | null>(() => {
    if (records.length === 0) return null;

    const byModel: AggregatedData["by_model"] = {};
    const byDate: AggregatedData["by_date"] = {};
    const byDateModel: AggregatedData["by_date_model"] = {};

    let totalPrompt = 0;
    let totalCompletion = 0;
    let totalCalls = 0;

    records.forEach((r) => {
      const pt = r.prompt_tokens;
      const ct = r.completion_tokens;
      const calls = r.call_count;
      const providerId = r.provider_id;
      totalPrompt += pt;
      totalCompletion += ct;
      totalCalls += calls;

      const modelKey = `${providerId}:${r.model}`;
      if (!byModel[modelKey]) {
        byModel[modelKey] = {
          model: r.model,
          provider_id: providerId,
          prompt_tokens: 0,
          completion_tokens: 0,
          call_count: 0,
        };
      }
      byModel[modelKey].prompt_tokens += pt;
      byModel[modelKey].completion_tokens += ct;
      byModel[modelKey].call_count += calls;

      if (!byDate[r.date]) {
        byDate[r.date] = {
          prompt_tokens: 0,
          completion_tokens: 0,
          call_count: 0,
        };
      }
      byDate[r.date].prompt_tokens += pt;
      byDate[r.date].completion_tokens += ct;
      byDate[r.date].call_count += calls;

      if (!byDateModel[r.date]) {
        byDateModel[r.date] = {};
      }
      if (!byDateModel[r.date][modelKey]) {
        byDateModel[r.date][modelKey] = {
          model: r.model,
          provider_id: providerId,
          prompt_tokens: 0,
          completion_tokens: 0,
          call_count: 0,
        };
      }
      byDateModel[r.date][modelKey].prompt_tokens += pt;
      byDateModel[r.date][modelKey].completion_tokens += ct;
      byDateModel[r.date][modelKey].call_count += calls;
    });

    return {
      total_prompt_tokens: totalPrompt,
      total_completion_tokens: totalCompletion,
      total_calls: totalCalls,
      by_model: byModel,
      by_date: byDate,
      by_date_model: byDateModel,
    };
  }, [records]);
}
