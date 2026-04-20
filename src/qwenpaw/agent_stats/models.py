# -*- coding: utf-8 -*-
"""Agent statistics models."""

from __future__ import annotations

from pydantic import BaseModel


class ChatStats(BaseModel):
    channel: str
    count: int


class MessageStats(BaseModel):
    channel: str
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


class AgentStatsSummary(BaseModel):
    total_chats: int
    chats_by_channel: list[ChatStats]
    total_messages: int
    total_user_messages: int
    total_assistant_messages: int
    messages_by_channel: list[MessageStats]
    total_prompt_tokens: int
    total_completion_tokens: int
    total_llm_calls: int
    total_tool_calls: int
    by_date: list[DailyStats]
    start_date: str
    end_date: str
