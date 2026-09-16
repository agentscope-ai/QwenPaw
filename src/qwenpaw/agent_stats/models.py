# -*- coding: utf-8 -*-
"""Agent statistics models."""

from __future__ import annotations

from pydantic import BaseModel


class ChannelStats(BaseModel):
    channel: str
    session_count: int
    user_messages: int
    assistant_messages: int
    total_messages: int


class DailyStats(BaseModel):
    date: str
    chats: int
    active_sessions: int
    user_messages: int
    assistant_messages: int
    total_messages: int
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    tool_calls: int
    # Current-agent daily token totals (independent of global overlay).
    agent_prompt_tokens: int = 0
    agent_completion_tokens: int = 0
    agent_llm_calls: int = 0
    agent_cache_read_tokens: int = 0


class AgentStatsSummary(BaseModel):
    total_active_sessions: int
    total_messages: int
    total_user_messages: int
    total_assistant_messages: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_llm_calls: int
    total_tool_calls: int
    by_date: list[DailyStats]
    channel_stats: list[ChannelStats]
    start_date: str
    end_date: str
    # Current-agent token totals from per-turn message metadata
    # (independent of the global total_*_tokens / by_date overlay).
    agent_prompt_tokens: int = 0
    agent_completion_tokens: int = 0
    agent_llm_calls: int = 0
    agent_cache_read_tokens: int = 0
    agent_cache_eligible_input_tokens: int = 0
    agent_cache_hit_rate: float | None = None


class LlmToolDaily(BaseModel):
    """Per-day LLM turns and tool calls aggregated across agents."""

    date: str
    agent_llm_calls: int = 0
    tool_calls: int = 0
