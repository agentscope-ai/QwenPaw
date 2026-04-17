# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from .models import CronJobSpec

logger = logging.getLogger(__name__)


async def _create_discord_thread(
    channel_manager: Any,
    channel_id: str,
    title: str,
) -> str:
    """Create a Discord thread in the given channel. Returns the thread ID."""
    import discord  # pylint: disable=import-outside-toplevel

    ch = await channel_manager.get_channel("discord")
    # pylint: disable=protected-access
    client = getattr(ch, "_client", None) if ch else None
    if client is None:
        raise RuntimeError("Discord channel not available")
    parent = client.get_channel(int(channel_id))
    if parent is None:
        parent = await client.fetch_channel(int(channel_id))
    thread = await parent.create_thread(
        name=title,
        type=discord.ChannelType.public_thread,
        auto_archive_duration=1440,
    )
    logger.info(
        "cron created thread: id=%s title=%s parent=%s",
        thread.id,
        title,
        channel_id,
    )
    return str(thread.id)


class CronExecutor:
    def __init__(self, *, runner: Any, channel_manager: Any):
        self._runner = runner
        self._channel_manager = channel_manager

    async def execute(self, job: CronJobSpec) -> None:
        """Execute one job once.

        - task_type text: send fixed text to channel
        - task_type agent: ask agent with prompt, send reply to channel (
            stream_query + send_event)

        When dispatch.create_thread is True (agent jobs only), a Discord
        thread is created first and all output is routed there.
        """
        target_user_id = job.dispatch.target.user_id
        target_session_id = job.dispatch.target.session_id
        dispatch_meta: Dict[str, Any] = dict(job.dispatch.meta or {})
        logger.info(
            "cron execute: job_id=%s channel=%s task_type=%s "
            "target_user_id=%s target_session_id=%s",
            job.id,
            job.dispatch.channel,
            job.task_type,
            target_user_id[:40] if target_user_id else "",
            target_session_id[:40] if target_session_id else "",
        )

        if job.task_type == "text" and job.text:
            logger.info(
                "cron send_text: job_id=%s channel=%s len=%s",
                job.id,
                job.dispatch.channel,
                len(job.text or ""),
            )
            await self._channel_manager.send_text(
                channel=job.dispatch.channel,
                user_id=target_user_id,
                session_id=target_session_id,
                text=job.text.strip(),
                meta=dispatch_meta,
            )
            return

        # agent: run request as the dispatch target user so context matches
        assert job.request is not None

        # Create thread if requested — rewrite session to thread
        if job.dispatch.create_thread and job.dispatch.channel == "discord":
            channel_id = target_session_id.split(":")[-1]
            date_str = datetime.now().strftime("%Y-%m-%d")
            title = (
                job.dispatch.thread_title or job.name + " {date}"
            ).replace("{date}", date_str)
            thread_id = await _create_discord_thread(
                self._channel_manager,
                channel_id,
                title,
            )
            target_session_id = f"discord:ch:{thread_id}"
            logger.info(
                "cron thread-first: job_id=%s thread_session=%s",
                job.id,
                target_session_id,
            )

        logger.info(
            "cron agent: job_id=%s channel=%s stream_query then send_event",
            job.id,
            job.dispatch.channel,
        )
        req: Dict[str, Any] = job.request.model_dump(mode="json")
        req["user_id"] = target_user_id or "cron"
        req["session_id"] = target_session_id or f"cron:{job.id}"

        async def _run() -> None:
            async for event in self._runner.stream_query(req):
                await self._channel_manager.send_event(
                    channel=job.dispatch.channel,
                    user_id=target_user_id,
                    session_id=target_session_id,
                    event=event,
                    meta=dispatch_meta,
                )

        try:
            await asyncio.wait_for(
                _run(),
                timeout=job.runtime.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "cron execute: job_id=%s timed out after %ss",
                job.id,
                job.runtime.timeout_seconds,
            )
            raise
        except asyncio.CancelledError:
            logger.info("cron execute: job_id=%s cancelled", job.id)
            raise
