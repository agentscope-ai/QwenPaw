export interface ChatStats {
  channel: string;
  count: number;
}

export interface MessageStats {
  channel: string;
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
}

export interface AgentStatsSummary {
  total_chats: number;
  chats_by_channel: ChatStats[];
  total_messages: number;
  total_user_messages: number;
  total_assistant_messages: number;
  messages_by_channel: MessageStats[];
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_llm_calls: number;
  total_tool_calls: number;
  by_date: DailyStats[];
  start_date: string;
  end_date: string;
}
