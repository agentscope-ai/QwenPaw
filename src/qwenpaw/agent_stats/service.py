# -*- coding: utf-8 -*-
"""Agent statistics service."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import aiofiles
import aiofiles.os
import orjson

from ..app.runner.repo import JsonChatRepository
from ..app.runner.session import sanitize_filename
from ..token_usage import get_token_usage_manager
from .models import (
    AgentStatsSummary,
    ChannelStats,
    DailyStats,
)

logger = logging.getLogger(__name__)


def _should_skip_by_mtime(
    session_file: Path,
    start_date: date,
    end_date: date,
) -> bool:
    try:
        mtime = session_file.stat().st_mtime
        mtime_date = date.fromtimestamp(mtime)
        buffered_end = end_date + timedelta(days=1)
        if mtime_date < start_date or mtime_date > buffered_end:
            logger.debug(
                "Skipping %s by mtime (%s) outside range [%s, %s]",
                session_file.name,
                mtime_date.isoformat(),
                start_date.isoformat(),
                end_date.isoformat(),
            )
            return True
    except OSError:
        pass
    return False


def _should_skip_by_content_range(
    session_data: dict,
    start_date_str: str,
    end_date_str: str,
) -> bool:
    memories = (
        session_data.get("agent", {}).get("memory", {}).get("memories")
    ) or session_data.get("agent", {}).get("memory", {}).get("content", [])

    if not memories:
        return True

    timestamps: list[str] = []
    for msg_item in memories:
        if isinstance(msg_item, list) and len(msg_item) > 0:
            msg_data = msg_item[0]
        elif isinstance(msg_item, dict):
            msg_data = msg_item
        else:
            continue

        if not isinstance(msg_data, dict):
            continue

        timestamp = msg_data.get("timestamp")
        if timestamp:
            timestamps.append(str(timestamp)[:10])

    if not timestamps:
        return True

    first_date = timestamps[0]
    last_date = timestamps[-1]

    if last_date < start_date_str or first_date > end_date_str:
        logger.debug(
            "Skipping session by content range [%s, %s] "
            "outside target [%s, %s]",
            first_date,
            last_date,
            start_date_str,
            end_date_str,
        )
        return True

    return False


# pylint:disable=too-many-statements,too-many-branches
def _process_session_file(
    session_data: dict,
    start_date_str: str,
    end_date_str: str,
    daily_stats: dict[str, dict],
    channel_stats: dict[str, dict],
    channel: str,
    session_stem: str,
    active_sessions: dict[str, set[str]],
) -> tuple[int, bool]:
    tool_call_count = 0
    has_messages_in_range = False
    try:
        memories = (
            session_data.get("agent", {}).get("memory", {}).get("memories")
        ) or session_data.get("agent", {}).get("memory", {}).get("content", [])

        stats = channel_stats.setdefault(
            channel,
            {
                "session_count": 0,
                "user_messages": 0,
                "assistant_messages": 0,
                "total_messages": 0,
            },
        )

        for msg_item in memories:
            if isinstance(msg_item, list) and len(msg_item) > 0:
                msg_data = msg_item[0]
            elif isinstance(msg_item, dict):
                msg_data = msg_item
            else:
                continue

            if not isinstance(msg_data, dict):
                continue

            timestamp = msg_data.get("timestamp")
            if not timestamp:
                continue

            date_str = str(timestamp)[:10]
            if date_str < start_date_str or date_str > end_date_str:
                continue

            has_messages_in_range = True
            active_sessions.setdefault(date_str, set()).add(session_stem)

            ds = daily_stats[date_str]
            role = msg_data.get("role", "")
            content = msg_data.get("content", [])

            if role == "user":
                ds["user_messages"] += 1
                ds["total_messages"] += 1
                stats["user_messages"] += 1
                stats["total_messages"] += 1
            elif role == "assistant":
                ds["assistant_messages"] += 1
                ds["total_messages"] += 1
                stats["assistant_messages"] += 1
                stats["total_messages"] += 1

            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                    ):
                        ds["tool_calls"] += 1
                        tool_call_count += 1

    except Exception as e:
        logger.debug("Failed to count messages in session: %s", e)

    if has_messages_in_range and channel in channel_stats:
        channel_stats[channel]["session_count"] += 1

    return tool_call_count, has_messages_in_range


class AgentStatsService:
    """Service for computing agent statistics."""

    # pylint: disable=R0912,R0915
    async def get_summary(
        self,
        workspace_dir: Path,
        start_date: date,
        end_date: date,
    ) -> AgentStatsSummary:
        chats_file = workspace_dir / "chats.json"
        sessions_dir = workspace_dir / "sessions"

        daily_stats: dict[str, dict] = {}
        days = (end_date - start_date).days + 1
        for i in range(days):
            date_str = (start_date + timedelta(days=i)).isoformat()
            daily_stats[date_str] = {
                "date": date_str,
                "chats": 0,
                "active_sessions": 0,
                "user_messages": 0,
                "assistant_messages": 0,
                "total_messages": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "llm_calls": 0,
                "tool_calls": 0,
            }

        start_date_str = start_date.isoformat()
        end_date_str = end_date.isoformat()

        channel_stats: dict[str, dict] = {}
        total_tool_calls = 0
        active_sessions: dict[str, set[str]] = {}
        total_active_sessions = 0

        session_file_to_channel: dict[str, str] = {}
        if chats_file.exists():
            try:
                repo = JsonChatRepository(chats_file)
                chats = await repo.list_chats()
                for chat in chats:
                    ch = chat.channel or "console"
                    safe_sid = sanitize_filename(chat.session_id)
                    safe_uid = (
                        sanitize_filename(chat.user_id) if chat.user_id else ""
                    )
                    session_file_to_channel[safe_sid] = ch
                    if safe_uid:
                        session_file_to_channel[f"{safe_uid}_{safe_sid}"] = ch
                    if chat.created_at is None:
                        continue
                    chat_date = chat.created_at.date()
                    if start_date <= chat_date <= end_date:
                        date_str = chat_date.isoformat()
                        daily_stats[date_str]["chats"] += 1
            except Exception as e:
                logger.warning("Failed to load chat statistics: %s", e)

        if sessions_dir.exists():
            try:
                session_names = await aiofiles.os.listdir(sessions_dir)
                session_files = [
                    sessions_dir / name
                    for name in session_names
                    if name.endswith(".json")
                ]

                session_fd_sem = asyncio.Semaphore((os.cpu_count() or 4) * 2)

                async def _process_one(session_file: Path) -> tuple[int, bool]:
                    if _should_skip_by_mtime(
                        session_file,
                        start_date,
                        end_date,
                    ):
                        return 0, False

                    try:
                        async with aiofiles.open(
                            session_file,
                            "r",
                            encoding="utf-8",
                        ) as f:
                            session_data = orjson.loads(await f.read())
                    except Exception as e:
                        logger.debug(
                            "Failed to read session file %s: %s",
                            session_file,
                            e,
                        )
                        return 0, False

                    if _should_skip_by_content_range(
                        session_data,
                        start_date_str,
                        end_date_str,
                    ):
                        return 0, False

                    stem = session_file.stem
                    channel = session_file_to_channel.get(stem, "console")

                    async with session_fd_sem:
                        return _process_session_file(
                            session_data,
                            start_date_str,
                            end_date_str,
                            daily_stats,
                            channel_stats,
                            channel,
                            stem,
                            active_sessions,
                        )

                tasks = [_process_one(sf) for sf in session_files]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, tuple) and len(result) == 2:
                        tool_calls, has_messages = result
                        total_tool_calls += tool_calls
                        if has_messages:
                            total_active_sessions += 1
                    elif isinstance(result, Exception):
                        logger.debug("Failed to process session: %s", result)
            except Exception as e:
                logger.warning("Failed to load message statistics: %s", e)

        token_summary = await get_token_usage_manager().get_summary(
            start_date=start_date,
            end_date=end_date,
        )
        for date_str, ts in token_summary.by_date.items():
            if date_str in daily_stats:
                daily_stats[date_str]["prompt_tokens"] = ts.prompt_tokens
                daily_stats[date_str][
                    "completion_tokens"
                ] = ts.completion_tokens
                daily_stats[date_str]["llm_calls"] = ts.call_count

        for date_str, session_set in active_sessions.items():
            if date_str in daily_stats:
                daily_stats[date_str]["active_sessions"] = len(session_set)

        by_date = [daily_stats[d] for d in sorted(daily_stats.keys())]

        total_user_messages = sum(ds["user_messages"] for ds in by_date)
        total_assistant_messages = sum(
            ds["assistant_messages"] for ds in by_date
        )
        total_messages = total_user_messages + total_assistant_messages

        return AgentStatsSummary(
            total_active_sessions=total_active_sessions,
            total_messages=total_messages,
            total_user_messages=total_user_messages,
            total_assistant_messages=total_assistant_messages,
            total_prompt_tokens=token_summary.total_prompt_tokens,
            total_completion_tokens=token_summary.total_completion_tokens,
            total_llm_calls=token_summary.total_calls,
            total_tool_calls=total_tool_calls,
            by_date=[DailyStats.model_validate(ds) for ds in by_date],
            channel_stats=[
                ChannelStats(
                    channel=ch,
                    session_count=cnts["session_count"],
                    user_messages=cnts["user_messages"],
                    assistant_messages=cnts["assistant_messages"],
                    total_messages=cnts["total_messages"],
                )
                for ch, cnts in sorted(channel_stats.items())
            ],
            start_date=start_date_str,
            end_date=end_date_str,
        )


_agent_stats_service: AgentStatsService | None = None


def get_agent_stats_service() -> AgentStatsService:
    global _agent_stats_service
    if _agent_stats_service is None:
        _agent_stats_service = AgentStatsService()
    return _agent_stats_service
