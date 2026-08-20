# -*- coding: utf-8 -*-
"""Agent statistics service."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import aiofiles
import aiofiles.os
import orjson

from ..app.chats.repo import JsonChatRepository
from ..token_usage import get_token_usage_manager
from ..token_usage.turn_usage import TURN_USAGE_META_KEY
from ..utils.io_utils import run_sync_io
from .models import (
    AgentStatsSummary,
    ChannelStats,
    DailyStats,
    LlmToolDaily,
)

logger = logging.getLogger(__name__)


# pylint: disable=unused-argument
def _should_skip_by_mtime(
    session_file: Path,
    start_date: date,
    end_date: date,
) -> bool:
    try:
        mtime = session_file.stat().st_mtime
        mtime_date = date.fromtimestamp(mtime)
        if mtime_date < start_date:
            logger.debug(
                "Skipping %s by mtime (%s) before start date %s",
                session_file.name,
                mtime_date.isoformat(),
                start_date.isoformat(),
            )
            return True
    except OSError:
        pass
    return False


def _extract_session_messages(session_data: dict) -> list:
    """Return raw message dicts/tuples from a session state, 1.x or 2.0."""
    agent_raw = session_data.get("agent", {})
    # 2.0: messages live on agent.state.context
    state_raw = agent_raw.get("state")
    if isinstance(state_raw, dict):
        ctx = state_raw.get("context")
        if isinstance(ctx, list) and ctx:
            return ctx
    # 1.x fallback
    memory_raw = agent_raw.get("memory", {})
    if isinstance(memory_raw, dict):
        return memory_raw.get("memories") or memory_raw.get("content") or []
    return []


def _iter_messages_in_range(
    session_data: dict,
    start_date_str: str,
    end_date_str: str,
) -> Iterator[tuple[str, dict]]:
    """Yield (date_str, msg_data) for calendar dates in the inclusive range."""
    for msg_item in _extract_session_messages(session_data):
        if isinstance(msg_item, list) and msg_item:
            msg_data = msg_item[0]
        elif isinstance(msg_item, dict):
            msg_data = msg_item
        else:
            continue
        if not isinstance(msg_data, dict):
            continue
        timestamp = msg_data.get("created_at") or msg_data.get("timestamp")
        if not timestamp:
            continue
        date_str = str(timestamp)[:10]
        if date_str < start_date_str or date_str > end_date_str:
            continue
        try:
            date.fromisoformat(date_str)
        except ValueError:
            continue
        yield date_str, msg_data


def _extract_turn_usage_tokens(msg_data: dict) -> tuple[int, int] | None:
    """Return (prompt, completion) from turn-usage metadata, or None."""
    meta = msg_data.get("metadata")
    if not isinstance(meta, dict):
        return None
    turn_meta = meta.get(TURN_USAGE_META_KEY)
    if not isinstance(turn_meta, dict):
        return None
    usage = turn_meta.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        pt = int(usage.get("prompt_tokens", 0) or 0)
        ct = int(usage.get("completion_tokens", 0) or 0)
    except (TypeError, ValueError):
        return None
    if pt <= 0 and ct <= 0:
        return None
    return pt, ct


def _assistant_turn_usage(msg_data: dict) -> tuple[int, int] | None:
    """Return turn usage for an assistant message, or None."""
    if msg_data.get("role") != "assistant":
        return None
    return _extract_turn_usage_tokens(msg_data)


def _count_tool_use_blocks(content: object) -> int:
    if not isinstance(content, list):
        return 0
    n = 0
    for block in content:
        btype = (
            block.get("type")
            if isinstance(block, dict)
            else getattr(block, "type", None)
        )
        if btype in ("tool_use", "tool_call"):
            n += 1
    return n


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
) -> tuple[int, bool, int, int, int]:
    tool_call_count = 0
    has_messages_in_range = False
    agent_prompt_tokens = 0
    agent_completion_tokens = 0
    agent_llm_calls = 0
    try:
        stats = channel_stats.setdefault(
            channel,
            {
                "session_count": 0,
                "user_messages": 0,
                "assistant_messages": 0,
                "total_messages": 0,
            },
        )

        for date_str, msg_data in _iter_messages_in_range(
            session_data,
            start_date_str,
            end_date_str,
        ):
            ds = daily_stats.get(date_str)
            if ds is None:
                continue
            has_messages_in_range = True
            active_sessions.setdefault(date_str, set()).add(session_stem)

            role = msg_data.get("role", "")

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

                # Current-agent token totals from per-turn metadata.
                # Do not write into daily_stats global token fields (overlay).
                tokens = _extract_turn_usage_tokens(msg_data)
                if tokens is not None:
                    pt, ct = tokens
                    agent_prompt_tokens += pt
                    agent_completion_tokens += ct
                    agent_llm_calls += 1
                    ds["agent_prompt_tokens"] += pt
                    ds["agent_completion_tokens"] += ct
                    ds["agent_llm_calls"] += 1

            n_tools = _count_tool_use_blocks(msg_data.get("content", []))
            ds["tool_calls"] += n_tools
            tool_call_count += n_tools

    except Exception as e:
        logger.warning("Failed to count messages in session: %s", e)

    if has_messages_in_range and channel in channel_stats:
        channel_stats[channel]["session_count"] += 1

    return (
        tool_call_count,
        has_messages_in_range,
        agent_prompt_tokens,
        agent_completion_tokens,
        agent_llm_calls,
    )


async def _list_session_json_files(
    sessions_dir: Path,
    *,
    strict: bool = False,
) -> list[Path]:
    session_files: list[Path] = []
    try:
        channel_names = await aiofiles.os.listdir(sessions_dir)
    except FileNotFoundError:
        return session_files
    for channel_name in channel_names:
        channel_path = sessions_dir / channel_name
        try:
            names = await aiofiles.os.listdir(channel_path)
        except NotADirectoryError:
            continue
        except Exception as e:
            logger.debug(
                "Failed to scan channel directory %s: %s",
                channel_path,
                e,
            )
            if strict:
                raise
            continue
        session_files.extend(
            channel_path / name for name in names if name.endswith(".json")
        )
    return session_files


async def _load_session_in_range(
    session_file: Path,
    start_date: date,
    end_date: date,
) -> dict | None:
    if _should_skip_by_mtime(session_file, start_date, end_date):
        return None
    try:
        async with aiofiles.open(session_file, encoding="utf-8") as f:
            session_data = orjson.loads(await f.read())
        if not isinstance(session_data, dict):
            return None
        return session_data
    except Exception as e:
        logger.debug("Failed to read session file %s: %s", session_file, e)
        return None


def _add_llm_tool_counts(
    session_data: dict,
    start_date_str: str,
    end_date_str: str,
    buckets: dict[str, dict[str, int]],
) -> None:
    try:
        for date_str, msg_data in _iter_messages_in_range(
            session_data,
            start_date_str,
            end_date_str,
        ):
            bucket = buckets.setdefault(
                date_str,
                {"agent_llm_calls": 0, "tool_calls": 0},
            )
            if _assistant_turn_usage(msg_data) is not None:
                bucket["agent_llm_calls"] += 1
            bucket["tool_calls"] += _count_tool_use_blocks(
                msg_data.get("content", []),
            )
    except Exception as e:
        logger.warning("Failed to count messages in session: %s", e)


_LLM_TOOL_WORKSPACE_CONCURRENCY = 4
_LLM_TOOL_ALL_FAILED = "llm/tool trend: all workspaces failed"
_LLM_TOOL_SOME_FAILED = "llm/tool trend: some workspaces failed"


def _stat_workspaces_sync() -> list[Path]:
    """Workspaces for global stats, including disabled agents.

    Same agent.json gate as get_agent_dirs, but missing paths are
    skipped and other OSError fails the trend.
    """
    from ..config.utils import iter_profile_workspace_paths

    seen: set[str] = set()
    dirs: list[Path] = []
    named = 0
    io_failed = 0
    for path in iter_profile_workspace_paths():
        named += 1
        try:
            path.stat()
            if not (path / "agent.json").exists():
                continue
            key = str(path.resolve())
        except FileNotFoundError:
            continue
        except OSError:
            io_failed += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        dirs.append(path)
    if io_failed or (named and not dirs):
        raise RuntimeError(
            _LLM_TOOL_ALL_FAILED if not dirs else _LLM_TOOL_SOME_FAILED,
        )
    return dirs


class AgentStatsService:
    """Service for computing agent statistics."""

    # pylint: disable=R0912,R0915
    async def get_summary(
        self,
        workspace_dir: Path,
        start_date: date,
        end_date: date,
    ) -> AgentStatsSummary:
        """Return stats for one workspace."""
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
                "agent_prompt_tokens": 0,
                "agent_completion_tokens": 0,
                "agent_llm_calls": 0,
            }

        start_date_str = start_date.isoformat()
        end_date_str = end_date.isoformat()

        channel_stats: dict[str, dict] = {}
        total_tool_calls = 0
        active_sessions: dict[str, set[str]] = {}
        total_active_sessions = 0
        agent_prompt_tokens = 0
        agent_completion_tokens = 0
        agent_llm_calls = 0

        if chats_file.exists():
            try:
                repo = JsonChatRepository(chats_file)
                chats = await repo.list_chats()
                for chat in chats:
                    if chat.created_at is None:
                        continue
                    chat_date = chat.created_at.date()
                    if start_date <= chat_date <= end_date:
                        date_str = chat_date.isoformat()
                        daily_stats[date_str]["chats"] += 1
            except Exception as e:
                logger.warning("Failed to load chat statistics: %s", e)

        # pylint: disable=too-many-nested-blocks
        if sessions_dir.exists():
            try:
                session_files = await _list_session_json_files(sessions_dir)
                fd_sem = asyncio.Semaphore((os.cpu_count() or 4) * 2)

                async def _process_one(
                    session_file: Path,
                ) -> tuple[int, bool, int, int, int]:
                    async with fd_sem:
                        session_data = await _load_session_in_range(
                            session_file,
                            start_date,
                            end_date,
                        )
                        if session_data is None:
                            return 0, False, 0, 0, 0
                        return _process_session_file(
                            session_data,
                            start_date_str,
                            end_date_str,
                            daily_stats,
                            channel_stats,
                            session_file.parent.name,
                            session_file.stem,
                            active_sessions,
                        )

                tasks = [_process_one(sf) for sf in session_files]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, tuple) and len(result) == 5:
                        (
                            tool_calls,
                            has_messages,
                            sess_prompt,
                            sess_completion,
                            sess_llm_calls,
                        ) = result
                        total_tool_calls += tool_calls
                        if has_messages:
                            total_active_sessions += 1
                        agent_prompt_tokens += sess_prompt
                        agent_completion_tokens += sess_completion
                        agent_llm_calls += sess_llm_calls
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
            agent_prompt_tokens=agent_prompt_tokens,
            agent_completion_tokens=agent_completion_tokens,
            agent_llm_calls=agent_llm_calls,
        )

    async def _workspace_llm_tool(
        self,
        workspace_dir: Path,
        start_date: date,
        end_date: date,
        session_fd_sem: asyncio.Semaphore,
    ) -> dict[str, dict[str, int]]:
        buckets: dict[str, dict[str, int]] = {}
        sessions_dir = workspace_dir / "sessions"
        session_files = await _list_session_json_files(
            sessions_dir,
            strict=True,
        )
        start_date_str = start_date.isoformat()
        end_date_str = end_date.isoformat()

        async def _one(session_file: Path) -> None:
            async with session_fd_sem:
                session_data = await _load_session_in_range(
                    session_file,
                    start_date,
                    end_date,
                )
                if session_data is not None:
                    _add_llm_tool_counts(
                        session_data,
                        start_date_str,
                        end_date_str,
                        buckets,
                    )

        await asyncio.gather(*[_one(sf) for sf in session_files])
        return buckets

    async def get_global_llm_tool_by_date(
        self,
        start_date: date,
        end_date: date,
    ) -> list[LlmToolDaily]:
        """Sum session LLM turns and tool calls across agent workspaces.

        Includes disabled agents (historical usage). Does not overlay
        global token-usage API call counts.
        """
        days = (end_date - start_date).days + 1
        totals: dict[str, dict[str, int]] = {}
        for i in range(days):
            date_str = (start_date + timedelta(days=i)).isoformat()
            totals[date_str] = {"agent_llm_calls": 0, "tool_calls": 0}

        workspaces = await run_sync_io(_stat_workspaces_sync)
        sem = asyncio.Semaphore(_LLM_TOOL_WORKSPACE_CONCURRENCY)
        session_fd_sem = asyncio.Semaphore((os.cpu_count() or 4) * 2)

        async def _one(path: Path) -> dict[str, dict[str, int]] | None:
            async with sem:
                try:
                    return await self._workspace_llm_tool(
                        path,
                        start_date,
                        end_date,
                        session_fd_sem,
                    )
                except Exception:
                    logger.warning(
                        "agent_stats: failed llm/tool trend for %s",
                        path,
                        exc_info=True,
                    )
                    return None

        results = await asyncio.gather(*[_one(p) for p in workspaces])
        failed = sum(1 for daily in results if daily is None)
        succeeded = len(results) - failed
        if failed:
            raise RuntimeError(
                _LLM_TOOL_ALL_FAILED
                if not succeeded
                else _LLM_TOOL_SOME_FAILED,
            )
        for daily in results:
            for date_str, counts in daily.items():
                bucket = totals.get(date_str)
                if bucket is None:
                    continue
                bucket["agent_llm_calls"] += counts["agent_llm_calls"]
                bucket["tool_calls"] += counts["tool_calls"]

        return [
            LlmToolDaily(date=date_str, **totals[date_str])
            for date_str in sorted(totals)
        ]


_agent_stats_service: AgentStatsService | None = None


def get_agent_stats_service() -> AgentStatsService:
    global _agent_stats_service
    if _agent_stats_service is None:
        _agent_stats_service = AgentStatsService()
    return _agent_stats_service
