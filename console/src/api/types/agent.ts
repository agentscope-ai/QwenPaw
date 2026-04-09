/** Agent query request payload. */
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

/** Mirrors Python AgentsRunningConfig. */
export interface AgentsRunningConfig {
  max_iters: number;
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
  /** Memory backend: 'remelight' (default) or 'adbpg'. */
  memory_manager_backend: "remelight" | "adbpg";
  /** ADBPG connection config (required when memory_manager_backend is 'adbpg'). */
  adbpg?: ADBPGConnectionConfig | null;
}

/** ADBPG connection and LLM/Embedding configuration. */
export interface ADBPGConnectionConfig {
  // --- Database connection ---
  host: string;
  port: number;
  user: string;
  password: string;
  dbname: string;
  // --- LLM configuration (used by adbpg_llm_memory) ---
  llm_model: string;
  llm_api_key: string;
  llm_base_url: string;
  // --- Embedding configuration ---
  embedding_model: string;
  embedding_api_key: string;
  embedding_base_url: string;
  embedding_dims: number;
  // --- Optional tuning ---
  /** Memory search timeout in seconds (default 10.0). */
  search_timeout: number;
  // --- Connection pool tuning ---
  /** Minimum connections in the shared pool (default 2). */
  pool_minconn: number;
  /** Maximum connections in the shared pool (default 10). */
  pool_maxconn: number;
  // --- Tool result compaction ---
  /** Compaction mode: 'summarize' (LLM) or 'truncate' (default 'summarize'). */
  tool_compact_mode: "summarize" | "truncate";
  /** Max character length after tool output compaction (default 500). */
  tool_compact_max_len: number;
  // --- Memory isolation ---
  /** When false (default), all agents share memory. When true, each agent's memory is isolated. */
  memory_isolation: boolean;
  /** When false (default), all users share memory. When true, memory is isolated per user_isolation_id. */
  user_isolation: boolean;
  /** User ID for memory isolation (only used when user_isolation is true). */
  user_isolation_id: string;
  /** When false (default), all sessions share memory. When true, memory is isolated per session run_id. */
  run_isolation: boolean;
  // --- API mode ---
  /** API mode: 'sql' (default, direct ADBPG SQL) or 'rest' (ADBPG memory REST API). */
  api_mode: "sql" | "rest";
  /** Custom fact extraction prompt for adbpg_llm_memory.config() (SQL mode only). */
  custom_fact_extraction_prompt: string;
  /** ADBPG memory REST API key (required when api_mode='rest'). */
  rest_api_key: string;
  /** ADBPG memory REST API base URL. */
  rest_base_url: string;
  /** When true, strip local-file memory instructions from AGENTS.md. */
  strip_local_memory_instructions: boolean;
}
