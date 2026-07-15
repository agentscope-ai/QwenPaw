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
}

export interface ToolResultPruningConfig {
  enabled: boolean;
  pruning_recent_n: number;
  pruning_old_msg_max_bytes: number;
  pruning_recent_msg_max_bytes: number;
  offload_retention_days: number;
  exempt_file_extensions: string[];
  exempt_tool_names: string[];
}

export type ContextStrategy = "native" | "scroll";

export interface LightContextConfig {
  strategy: ContextStrategy;
  dialog_path: string;
  token_count_estimate_divisor: number;
  context_compact_config: ContextCompactConfig;
  tool_result_pruning_config: ToolResultPruningConfig;
}

export interface AutoMemorySearchConfig {
  enabled: boolean;
  max_results: number;
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
  auto_memory_interval: number;
  dream_cron: string;
  auto_memory_search_config: AutoMemorySearchConfig;
  embedding_model_config: EmbeddingModelConfig;
  rebuild_memory_index_on_start: boolean;
}

export interface AutoTitleConfig {
  enabled: boolean;
  timeout_seconds: number;
}

export interface ADBPGMemoryConfig {
  rest_base_url: string;
  rest_api_key: string;
  memory_isolation: boolean;
  search_timeout: number;
  auto_memory_search_config: AutoMemorySearchConfig;
}

export interface DoomLoopStageConfig {
  after: number;
  action: string;
  prompt: string;
}

export interface DoomLoopConfig {
  enabled: boolean;
  window_size: number;
  similarity_threshold: number;
  stages: DoomLoopStageConfig[];
}

export interface IterationGateConfig {
  enabled: boolean;
  max_iterations?: number | null;
}

export interface RubricGateConfig {
  enabled: boolean;
  prompt: string;
  max_interventions: number;
  in_loop_modes: boolean;
}

export interface LoopConfig {
  iteration?: IterationGateConfig;
  doom_loop: DoomLoopConfig;
  rubric?: RubricGateConfig;
}

export interface AgentsRunningConfig {
  max_iters: number;
  loop: LoopConfig;
  shell_command_timeout: number;
  shell_command_executable: string;
  llm_retry_enabled: boolean;
  llm_max_retries: number;
  llm_backoff_base: number;
  llm_backoff_cap: number;
  llm_max_concurrent: number;
  llm_max_qpm: number;
  llm_rate_limit_pause: number;
  llm_rate_limit_jitter: number;
  llm_acquire_timeout: number;
  history_max_length: number;
  context_manager_backend: string;
  light_context_config: LightContextConfig;
  memory_manager_backend: string;
  adbpg_memory_config?: ADBPGMemoryConfig | null;
  reme_light_memory_config: ReMeLightMemoryConfig;
  approval_level?: string;
  auto_title_config: AutoTitleConfig;
}
