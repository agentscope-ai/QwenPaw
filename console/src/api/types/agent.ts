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
  tool_result_compact_recent_n: number;
  tool_result_compact_old_threshold: number;
  tool_result_compact_recent_threshold: number;
  tool_result_compact_retention_days: number;
}
