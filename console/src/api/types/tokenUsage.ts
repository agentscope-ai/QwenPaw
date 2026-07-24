/** Single token usage record (per date + provider + model + user). */
export interface TokenUsageRecord {
  date: string; // YYYY-MM-DD
  provider_id: string;
  model: string;
  /** Caller the usage is billed to; "system" / "unknown" are reserved. */
  user_id: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
}

/** Per-model (has provider_id, model) or per-date (no provider_id, model) stats. */
export interface TokenUsageStats {
  provider_id?: string;
  model?: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
}

export interface TokenUsageSummary {
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_calls: number;
  by_model: Record<string, TokenUsageStats>;
  by_date: Record<string, TokenUsageStats>;
  by_user: Record<string, TokenUsageStats>;
}
