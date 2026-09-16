# -*- coding: utf-8 -*-
"""多用户 Agent 统计的 PostgreSQL 匿名聚合。"""

from __future__ import annotations

import re
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime, time, timedelta
from typing import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..access.agent_repository import agent_database_id
from ..persistence.database import database_session
from ..token_usage.manager import TokenUsageSummary
from .models import AgentStatsSummary, ChannelStats, DailyStats

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class PostgresAgentStatsRepository:
    def __init__(
        self,
        *,
        schema: str,
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("invalid_database_schema")
        self.schema = normalized
        self._session_factory = session_factory

    def table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    async def get_summary(
        self,
        *,
        agent_key: str,
        viewer_user_id: UUID,
        aggregate_all: bool,
        start_date: date,
        end_date: date,
        token_summary: TokenUsageSummary,
    ) -> AgentStatsSummary:
        started_at = datetime.combine(start_date, time.min, tzinfo=UTC)
        ended_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        owner_clause = "" if aggregate_all else "AND c.owner_user_id=:viewer_user_id"
        params = {
            "agent_id": agent_database_id(agent_key),
            "viewer_user_id": viewer_user_id,
            "started_at": started_at,
            "ended_at": ended_at,
        }
        async with self._session_factory() as session:
            conversation_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT to_char(c.created_at AT TIME ZONE 'UTC','YYYY-MM-DD') AS date,"
                            "count(*) AS chats "
                            f"FROM {self.table('conversations')} c "
                            "WHERE c.agent_id=:agent_id AND c.deleted_at IS NULL "
                            "AND c.created_at>=:started_at AND c.created_at<:ended_at "
                            f"{owner_clause} GROUP BY 1"
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            message_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT to_char(m.created_at AT TIME ZONE 'UTC','YYYY-MM-DD') AS date,"
                            "count(DISTINCT c.id) AS active_sessions,"
                            "count(*) FILTER (WHERE m.role='user') AS user_messages,"
                            "count(*) FILTER (WHERE m.role='assistant') AS assistant_messages "
                            f"FROM {self.table('messages')} m "
                            f"JOIN {self.table('conversations')} c ON c.id=m.conversation_id "
                            "WHERE c.agent_id=:agent_id AND c.deleted_at IS NULL "
                            "AND m.created_at>=:started_at AND m.created_at<:ended_at "
                            f"{owner_clause} GROUP BY 1"
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            total_sessions = int(
                await session.scalar(
                    text(
                        "SELECT count(DISTINCT c.id) "
                        f"FROM {self.table('messages')} m "
                        f"JOIN {self.table('conversations')} c ON c.id=m.conversation_id "
                        "WHERE c.agent_id=:agent_id AND c.deleted_at IS NULL "
                        "AND m.created_at>=:started_at AND m.created_at<:ended_at "
                        f"{owner_clause}"
                    ),
                    params,
                )
                or 0
            )
            tool_rows = (
                (
                    await session.execute(
                        text(
                            "SELECT to_char(tc.started_at AT TIME ZONE 'UTC','YYYY-MM-DD') AS date,"
                            "count(*) AS tool_calls "
                            f"FROM {self.table('tool_calls')} tc "
                            f"JOIN {self.table('runs')} r ON r.id=tc.run_id "
                            f"JOIN {self.table('conversations')} c ON c.id=r.conversation_id "
                            "WHERE c.agent_id=:agent_id AND c.deleted_at IS NULL "
                            "AND tc.started_at>=:started_at AND tc.started_at<:ended_at "
                            f"{owner_clause} GROUP BY 1"
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )

        days = (end_date - start_date).days + 1
        daily = {
            (start_date + timedelta(days=index)).isoformat(): {
                "chats": 0,
                "active_sessions": 0,
                "user_messages": 0,
                "assistant_messages": 0,
                "tool_calls": 0,
            }
            for index in range(days)
        }
        for row in conversation_rows:
            daily[row["date"]]["chats"] = int(row["chats"])
        for row in message_rows:
            bucket = daily[row["date"]]
            for key in ("active_sessions", "user_messages", "assistant_messages"):
                bucket[key] = int(row[key])
        for row in tool_rows:
            daily[row["date"]]["tool_calls"] = int(row["tool_calls"])

        by_date = []
        for date_key, values in daily.items():
            token_day = token_summary.by_date.get(date_key)
            prompt = token_day.prompt_tokens if token_day else 0
            completion = token_day.completion_tokens if token_day else 0
            calls = token_day.call_count if token_day else 0
            by_date.append(
                DailyStats(
                    date=date_key,
                    total_messages=values["user_messages"]
                    + values["assistant_messages"],
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    llm_calls=calls,
                    agent_prompt_tokens=prompt,
                    agent_completion_tokens=completion,
                    agent_llm_calls=calls,
                    **values,
                )
            )
        total_user = sum(row.user_messages for row in by_date)
        total_assistant = sum(row.assistant_messages for row in by_date)
        return AgentStatsSummary(
            total_active_sessions=total_sessions,
            total_messages=total_user + total_assistant,
            total_user_messages=total_user,
            total_assistant_messages=total_assistant,
            total_prompt_tokens=token_summary.total_prompt_tokens,
            total_completion_tokens=token_summary.total_completion_tokens,
            total_llm_calls=token_summary.total_calls,
            total_tool_calls=sum(row.tool_calls for row in by_date),
            by_date=by_date,
            channel_stats=[
                ChannelStats(
                    channel="console",
                    session_count=total_sessions,
                    user_messages=total_user,
                    assistant_messages=total_assistant,
                    total_messages=total_user + total_assistant,
                )
            ]
            if total_sessions
            else [],
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            agent_prompt_tokens=token_summary.total_prompt_tokens,
            agent_completion_tokens=token_summary.total_completion_tokens,
            agent_llm_calls=token_summary.total_calls,
        )


__all__ = ["PostgresAgentStatsRepository"]
