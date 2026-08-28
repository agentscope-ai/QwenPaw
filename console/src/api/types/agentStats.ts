export interface ChannelStats {
  channel: string;
  session_count: number;
  user_messages: number;
  assistant_messages: number;
  total_messages: number;
}

export interface DailyStats {
  date: string;
  chats: number;
  active_sessions: number;
  user_messages: number;
  assistant_messages: number;
  total_messages: number;
  prompt_tokens: number;
  completion_tokens: number;
  llm_calls: number;
  tool_calls: number;
  /** Current-agent daily token totals from per-turn session metadata. */
  agent_prompt_tokens?: number;
  agent_completion_tokens?: number;
  agent_llm_calls?: number;
  agent_cache_read_tokens: number;
}

export interface AgentStatsSummary {
  total_active_sessions: number;
  total_messages: number;
  total_user_messages: number;
  total_assistant_messages: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_llm_calls: number;
  total_tool_calls: number;
  by_date: DailyStats[];
  channel_stats: ChannelStats[];
  start_date: string;
  end_date: string;
  /** Current-agent token totals from per-turn session metadata. */
  agent_prompt_tokens?: number;
  agent_completion_tokens?: number;
  agent_llm_calls?: number;
  agent_cache_read_tokens: number;
  agent_cache_eligible_input_tokens: number;
  agent_cache_hit_rate: number | null;
}
