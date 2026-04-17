export interface AgentRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  channel?: string | null;
  [key: string]: unknown;
}

export interface ContextCompactConfig {
  enabled: boolean;
  compact_threshold_ratio: number;
  reserve_threshold_ratio: number;
  compact_with_thinking_block: boolean;
}

export interface ToolResultPruningConfig {
  enabled: boolean;
  pruning_recent_n: number;
  pruning_old_msg_max_bytes: number;
  pruning_recent_msg_max_bytes: number;
  offload_retention_days: number;
}

export interface LightContextConfig {
  dialog_path: string;
  token_count_estimate_divisor: number;
  context_compact_config: ContextCompactConfig;
  tool_result_pruning_config: ToolResultPruningConfig;
}

export interface ForceMemorySearchConfig {
  enabled: boolean;
  max_results: number;
  min_score: number;
}

export interface EmbeddingModelConfig {
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

export interface ReMeLightMemoryConfig {
  summarize_when_compact: boolean;
  summarize_interval: number | null;
  dream_cron: string;
  force_memory_search_config: ForceMemorySearchConfig;
  embedding_model_config: EmbeddingModelConfig;
  rebuild_memory_index_on_start: boolean;
  recursive_file_watcher: boolean;
}

export interface AgentsRunningConfig {
  max_iters: number;
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
  context_manager_backend: string;
  light_context_config: LightContextConfig;
  memory_manager_backend: string;
  reme_light_memory_config: ReMeLightMemoryConfig;
}