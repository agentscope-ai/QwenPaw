export interface AgentRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  channel?: string | null;
  [key: string]: unknown;
}

export interface AgentsRunningConfig {
  max_iters: number;
  llm_retry_enabled: boolean;
  llm_max_retries: number;
  llm_backoff_base: number;
  llm_backoff_cap: number;
  token_count_model?: string;
  token_count_estimate_divisor?: number;
  token_count_use_mirror?: boolean;
  max_input_length: number;
  memory_compact_ratio: number;
  memory_reserve_ratio: number;
  tool_result_compact_recent_n: number;
  tool_result_compact_old_threshold: number;
  tool_result_compact_recent_threshold: number;
  tool_result_compact_retention_days: number;
  history_max_length?: number;
  compact_with_thinking_block?: boolean;
  knowledge_enabled: boolean;
  knowledge_auto_collect_chat_files: boolean;
  knowledge_auto_collect_chat_urls: boolean;
  knowledge_auto_collect_long_text: boolean;
  knowledge_long_text_min_chars: number;
  knowledge_chunk_size: number;
  embedding_config?: Record<string, object | undefined>;
}
