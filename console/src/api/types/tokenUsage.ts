export interface TokenUsageByModel {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  call_count: number;
}

export interface TokenUsageSummary {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  total_calls: number;
  by_model: Record<string, TokenUsageByModel>;
  by_date: Record<string, TokenUsageByModel>;
}
