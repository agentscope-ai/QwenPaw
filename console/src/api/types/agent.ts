export interface AgentRequest {
  input: unknown;
  session_id?: string | null;
  user_id?: string | null;
  channel?: string | null;
  [key: string]: unknown;
}

export interface AgentsRunningConfig {
  max_iters: number;
  max_input_length: number;
  memory_compact_ratio: number;
  memory_reserve_ratio: number;
  enable_tool_result_compact: boolean;
  tool_result_compact_keep_n: number;
  knowledge_enabled: boolean;
  knowledge_auto_collect_chat_files: boolean;
  knowledge_auto_collect_chat_urls: boolean;
  knowledge_auto_collect_long_text: boolean;
  knowledge_long_text_min_chars: number;
  knowledge_chunk_size: number;
}
