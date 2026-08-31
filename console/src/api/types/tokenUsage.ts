/** Single token usage record (per date + agent + provider + model). */
export interface TokenUsageRecord {
  date: string; // YYYY-MM-DD
  provider_id: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_eligible_input_tokens: number;
  cache_observed_calls: number;
  call_count: number;
  agent_id?: string | null;
}

/** Per-model (has provider_id, model) or per-date (no provider_id, model) stats. */
export interface TokenUsageStats {
  provider_id?: string;
  model?: string;
  prompt_tokens: number;
  completion_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_eligible_input_tokens: number;
  cache_observed_calls: number;
  call_count: number;
}

export interface TokenUsageSummary {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cache_read_tokens: number;
  total_cache_write_tokens: number;
  total_cache_eligible_input_tokens: number;
  cache_observed_calls: number;
  cache_hit_rate: number | null;
  total_calls: number;
  by_model: Record<string, TokenUsageStats>;
  by_date: Record<string, TokenUsageStats>;
}
