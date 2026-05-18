# -*- coding: utf-8 -*-
"""
Heartbeat: run agent with HEARTBEAT.md as query at interval.
Uses config functions (get_heartbeat_config, get_heartbeat_query_path,
load_config) for paths and settings.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Dict, Optional

from ...agents.utils.file_handling import read_text_file_with_encoding_fallback
from ...config import (
    get_heartbeat_config,
    get_heartbeat_query_path,
    load_config,
)
from ...constant import (
    HEARTBEAT_FILE,
    HEARTBEAT_TARGET_INBOX,
    HEARTBEAT_TARGET_LAST,
)
from ..channels.schema import DEFAULT_CHANNEL
from ..inbox_store import append_event as append_inbox_event
from ..inbox_trace_store import (
    append_trace_from_session_delta,
    create_trace,
    finalize_trace,
    read_session_messages,
)
from ..crons.models import _crontab_dow_to_name

logger = logging.getLogger(__name__)

# Pattern for "30m", "1h", "2h30m", "90s"
_EVERY_PATTERN = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$",
    re.IGNORECASE,
)

# 5-field cron: minute hour day month day_of_week
_CRON_FIELD_PATTERN = re.compile(
    r"^[\d\*\-/,]+$",
)
_HEARTBEAT_SOURCE_ID = "_heartbeat"


def is_cron_expression(every: str) -> bool:
    """Return True if *every* looks like a 5-field cron expression."""
    parts = (every or "").strip().split()
    if len(parts) != 5:
        return False
    return all(_CRON_FIELD_PATTERN.match(p) for p in parts)


def parse_heartbeat_cron(every: str) -> tuple:
    """Parse and normalize a 5-field cron string.

    Returns (minute, hour, day, month, dow).
    """
    parts = every.strip().split()
    if len(parts) == 5:
        parts[4] = _crontab_dow_to_name(parts[4])
    return tuple(parts)


def parse_heartbeat_every(every: str) -> int:
    """Parse interval string (e.g. '30m', '1h') to total seconds.

    Note: cron expressions should be detected via ``is_cron_expression``
    *before* calling this function.
    """
    every = (every or "").strip()
    if not every:
        return 30 * 60  # default 30 min
    m = _EVERY_PATTERN.match(every)
    if not m:
        logger.warning("heartbeat every=%r invalid, using 30m", every)
        return 30 * 60
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = int(m.group("seconds") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        return 30 * 60
    return total


def _in_active_hours(active_hours: Any) -> bool:
    """Return True if the current time in user timezone is within
    [start, end].
    """
    if (
        not active_hours
        or not hasattr(active_hours, "start")
        or not hasattr(active_hours, "end")
    ):
        return True
    try:
        start_parts = active_hours.start.strip().split(":")
        end_parts = active_hours.end.strip().split(":")
        start_t = time(
            int(start_parts[0]),
            int(start_parts[1]) if len(start_parts) > 1 else 0,
        )
        end_t = time(
            int(end_parts[0]),
            int(end_parts[1]) if len(end_parts) > 1 else 0,
        )
    except (ValueError, IndexError, AttributeError):
        return True
    user_tz = load_config().user_timezone or "UTC"
    try:
        now = datetime.now(ZoneInfo(user_tz)).time()
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning(
            "Invalid timezone %r in config, falling back to UTC"
            " for heartbeat active hours check.",
            user_tz,
        )
        now = datetime.now(timezone.utc).time()
    if start_t <= end_t:
        return start_t <= now <= end_t
    return now >= start_t or now <= end_t


def _extract_message_preview(msg: dict[str, Any]) -> str | None:
    content = msg.get("content")
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif btype == "thinking" and isinstance(block.get("thinking"), str):
            parts.append(block["thinking"])
        elif btype == "tool_result":
            output = block.get("output")
            if isinstance(output, list):
                for out_block in output:
                    if (
                        isinstance(out_block, dict)
                        and out_block.get("type") == "text"
                        and isinstance(out_block.get("text"), str)
                    ):
                        parts.append(out_block["text"])
    text = "\n".join([p.strip() for p in parts if p and p.strip()]).strip()
    return text or None


def _last_preview_from_delta(delta: list[dict[str, Any]]) -> str | None:
    for msg in reversed(delta):
        preview = _extract_message_preview(msg)
        if preview:
            return preview
    return None


# pylint: disable=too-many-branches,too-many-statements
async def run_heartbeat_once(
    *,
    runner: Any,
    channel_manager: Any,
    agent_id: Optional[str] = None,
    workspace_dir: Optional[Path] = None,
) -> None:
    """
    Run one heartbeat: read HEARTBEAT.md from workspace, run agent,
    optionally dispatch to last channel (target=last).

    Args:
        runner: Agent runner instance
        channel_manager: Channel manager instance
        agent_id: Agent ID for loading config
        workspace_dir: Workspace directory for reading HEARTBEAT.md
    """
    from ...config.config import load_agent_config

    hb = get_heartbeat_config(agent_id)
    if not _in_active_hours(hb.active_hours):
        logger.debug("heartbeat skipped: outside active hours")
        return

    # Use workspace_dir if provided, otherwise fall back to global path
    if workspace_dir:
        path = Path(workspace_dir) / HEARTBEAT_FILE
    else:
        path = get_heartbeat_query_path()

    if not path.is_file():
        logger.debug("heartbeat skipped: no file at %s", path)
        return

    query_text = read_text_file_with_encoding_fallback(path).strip()
    if not query_text:
        logger.debug("heartbeat skipped: empty query file")
        return

    # Build request: single user message with query text
    req: Dict[str, Any] = {
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": query_text}],
            },
        ],
        "session_id": "main",
        "user_id": "main",
        "channel": DEFAULT_CHANNEL,
    }

    # Get last_dispatch from agent config if agent_id provided
    last_dispatch = None
    if agent_id:
        try:
            agent_config = load_agent_config(agent_id)
            last_dispatch = agent_config.last_dispatch
        except Exception:
            pass
    else:
        # Legacy: try root config
        config = load_config()
        last_dispatch = config.last_dispatch

    target = (hb.target or "").strip().lower()
    if target == HEARTBEAT_TARGET_LAST and last_dispatch:
        ld = last_dispatch
        if ld.channel and (ld.user_id or ld.session_id):

            async def _run_and_dispatch() -> None:
                async for event in runner.stream_query(req):
                    await channel_manager.send_event(
                        channel=ld.channel,
                        user_id=ld.user_id,
                        session_id=ld.session_id,
                        event=event,
                        meta={},
                    )

            try:
                await asyncio.wait_for(_run_and_dispatch(), timeout=120)
            except asyncio.TimeoutError:
                logger.warning("heartbeat run timed out")
            return

    if target == HEARTBEAT_TARGET_INBOX:
        run_id = str(uuid.uuid4())
        baseline_messages = await read_session_messages(
            runner=runner,
            session_id=req["session_id"],
            user_id=req["user_id"],
            channel=req["channel"],
        )
        baseline_count = len(baseline_messages)
        await create_trace(
            run_id,
            meta={
                "source": "heartbeat",
                "task_type": "agent",
                "target": target,
                "query_file": str(path),
                "agent_id": agent_id,
                "session_id": req["session_id"],
                "user_id": req["user_id"],
                "channel": req["channel"],
            },
        )

        async def _run_only() -> None:
            async for _ in runner.stream_query(req):
                pass

        try:
            await asyncio.wait_for(_run_only(), timeout=120)
            delta = await append_trace_from_session_delta(
                run_id=run_id,
                runner=runner,
                session_id=req["session_id"],
                user_id=req["user_id"],
                channel=req["channel"],
                baseline_count=baseline_count,
            )
            await finalize_trace(run_id, status="success")
            body = _last_preview_from_delta(delta) or (
                "Heartbeat task finished successfully."
            )
            await append_inbox_event(
                agent_id=agent_id,
                source_type="heartbeat",
                source_id=_HEARTBEAT_SOURCE_ID,
                event_type="heartbeat_result",
                status="success",
                severity="info",
                title="Heartbeat result",
                body=body,
                payload={
                    "run_id": run_id,
                    "target": target,
                    "query_file": str(path),
                },
            )
        except asyncio.TimeoutError:
            logger.warning("heartbeat run timed out")
            await append_trace_from_session_delta(
                run_id=run_id,
                runner=runner,
                session_id=req["session_id"],
                user_id=req["user_id"],
                channel=req["channel"],
                baseline_count=baseline_count,
            )
            await finalize_trace(
                run_id,
                status="timeout",
                error="timed out after 120s",
            )
            await append_inbox_event(
                agent_id=agent_id,
                source_type="heartbeat",
                source_id=_HEARTBEAT_SOURCE_ID,
                event_type="heartbeat_timeout",
                status="error",
                severity="error",
                title="Heartbeat timed out",
                body="Heartbeat run timed out after 120s.",
                payload={
                    "run_id": run_id,
                    "target": target,
                    "query_file": str(path),
                },
            )
        except Exception as e:  # pylint: disable=broad-except
            logger.exception("heartbeat run failed (inbox target)")
            await append_trace_from_session_delta(
                run_id=run_id,
                runner=runner,
                session_id=req["session_id"],
                user_id=req["user_id"],
                channel=req["channel"],
                baseline_count=baseline_count,
            )
            await finalize_trace(run_id, status="error", error=repr(e))
            await append_inbox_event(
                agent_id=agent_id,
                source_type="heartbeat",
                source_id=_HEARTBEAT_SOURCE_ID,
                event_type="heartbeat_error",
                status="error",
                severity="error",
                title="Heartbeat execution failed",
                body=repr(e),
                payload={
                    "run_id": run_id,
                    "target": target,
                    "query_file": str(path),
                },
            )
            raise
        return

    # target main or no last_dispatch: run agent only, no dispatch
    async def _run_without_dispatch() -> None:
        async for _ in runner.stream_query(req):
            pass

    try:
        await asyncio.wait_for(_run_without_dispatch(), timeout=120)
    except asyncio.TimeoutError:
        logger.warning("heartbeat run timed out")
