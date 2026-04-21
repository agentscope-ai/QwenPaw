export interface AgentRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  channel?: string | null;
  [key: string]: unknown;
}

export interface ContextCompactConfig {
  token_count_model: string;
  token_count_use_mirror: boolean;
  token_count_estimate_divisor: number;
  context_compact_enabled: boolean;
  memory_compact_ratio: number;
  memory_reserve_ratio: number;
  compact_with_thinking_block: boolean;
}

export interface ToolResultCompactConfig {
  enabled: boolean;
  recent_n: number;
  old_max_bytes: number;
  recent_max_bytes: number;
  retention_days: number;
}

export interface MemorySummaryConfig {
  memory_summary_enabled: boolean;
  dream_cron: string;
  force_memory_search: boolean;
  force_max_results: number;
  force_min_score: number;
  rebuild_memory_index_on_start: boolean;
}

export interface EmbeddingConfig {
  backend: string;
  api_key: string;
  base_url: string;
  model_name: string;
  dimensions: number;
  enable_cache: boolean;
  use_dimensions: boolean;
  max_cache_size: number;
  max_input_length: number;
  max_batch_size: number;
}

export interface AgentsRunningConfig {
  max_iters: number;
  /** When true, inject a hint and one extra reasoning pass if the model returns text-only (no tool calls). */
  auto_continue_on_text_only: boolean;
  llm_retry_enabled: boolean;
  llm_max_retries: number;
  llm_backoff_base: number;
  llm_backoff_cap: number;
  llm_max_concurrent: number;
  llm_max_qpm: number;
  llm_rate_limit_pause: number;
  llm_rate_limit_jitter: number;
  llm_acquire_timeout: number;
  max_input_length: number;
  history_max_length: number;
  context_compact: ContextCompactConfig;
  tool_result_compact: ToolResultCompactConfig;
  memory_summary: MemorySummaryConfig;
  embedding_config: EmbeddingConfig;
  memory_manager_backend: "remelight";
  enable_plan_notebook: boolean;
}
