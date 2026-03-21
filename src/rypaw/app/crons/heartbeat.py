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
from datetime import datetime, time
from typing import Any, Dict

from ...config import (
    get_heartbeat_config,
    get_heartbeat_query_path,
    load_config,
)
from ...constant import HEARTBEAT_TARGET_LAST

logger = logging.getLogger(__name__)

# Pattern for "30m", "1h", "2h30m", "90s"
_EVERY_PATTERN = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$",
    re.IGNORECASE,
)


def parse_heartbeat_every(every: str) -> int:
    """Parse interval string (e.g. '30m', '1h') to total seconds."""
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
    """Return True if current local time is within [start, end]."""
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
    now = datetime.now().time()
    if start_t <= end_t:
        return start_t <= now <= end_t
    return now >= start_t or now <= end_t


async def run_heartbeat_once(
    *,
    runner: Any,
    channel_manager: Any,
) -> None:
    """
    Run one heartbeat: read HEARTBEAT.md via config path, run agent,
    optionally dispatch to last channel (target=last).
    """
    config = load_config()
    hb = get_heartbeat_config()
    if not _in_active_hours(hb.active_hours):
        logger.debug("heartbeat skipped: outside active hours")
        return

    path = get_heartbeat_query_path()
    if not path.is_file():
        logger.debug("heartbeat skipped: no file at %s", path)
        return

    query_text = path.read_text(encoding="utf-8").strip()
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
    }

    target = (hb.target or "").strip().lower()
    if target == HEARTBEAT_TARGET_LAST and config.last_dispatch:
        ld = config.last_dispatch
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

    # target main or no last_dispatch: run agent only, no dispatch
    async def _run_only() -> None:
        async for _ in runner.stream_query(req):
            pass

    try:
        await asyncio.wait_for(_run_only(), timeout=120)
    except asyncio.TimeoutError:
        logger.warning("heartbeat run timed out")
