# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict
from zoneinfo import ZoneInfo

from .models import CronJobSpec

logger = logging.getLogger(__name__)


class CronExecutor:
    def __init__(self, *, runner: Any, channel_manager: Any):
        self._runner = runner
        self._channel_manager = channel_manager

    async def execute(self, job: CronJobSpec) -> None:
        """Execute one job once.

        - task_type text: send fixed text to channel
        - task_type agent: ask agent with prompt, send reply to channel (
            stream_query + send_event)

        When dispatch.create_thread is True (agent jobs only), the target
        channel's begin_subthread() is called first and all agent output is
        routed to the returned sub-thread session. Channels without native
        thread support inherit a no-op default from BaseChannel.
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

        # Create a sub-thread if requested — rewrite session to the thread.
        # Channels without thread support inherit BaseChannel's no-op default.
        if job.dispatch.create_thread:
            ch = await self._channel_manager.get_channel(job.dispatch.channel)
            if ch is None:
                raise RuntimeError(
                    f"channel not available: {job.dispatch.channel}",
                )
            tz = ZoneInfo(job.schedule.timezone)
            date_str = datetime.now(tz).strftime("%Y-%m-%d")
            title_template = (
                job.dispatch.thread_title or f"{job.name} {{date}}"
            )
            title = title_template.replace("{date}", date_str)
            target_session_id = await ch.begin_subthread(
                user_id=target_user_id or "",
                session_id=target_session_id or "",
                title=title,
            )
            logger.info(
                "cron begin_subthread: job_id=%s channel=%s session=%s",
                job.id,
                job.dispatch.channel,
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
