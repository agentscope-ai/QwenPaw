# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict
from uuid import uuid4

from .models import CronJobSpec

logger = logging.getLogger(__name__)


def _generate_execution_session_id(job_id: str) -> str:
    timestamp = int(time.time() * 1000)
    uuid_short = str(uuid4())[:8]
    return f"cron:{job_id}:{timestamp}:{uuid_short}"


class CronExecutor:
    def __init__(self, *, runner: Any, channel_manager: Any):
        self._runner = runner
        self._channel_manager = channel_manager

    async def execute(self, job: CronJobSpec) -> None:
        """Execute one job once.

        - task_type text: send fixed text to channel
        - task_type agent: ask agent with prompt, send reply to channel (
            stream_query + send_event)
        """
        target_user_id = job.dispatch.target.user_id
        dispatch_session_id = job.dispatch.target.session_id
        session_mode = job.execution.session.mode
        execution_session_id = (
            _generate_execution_session_id(job.id)
            if session_mode == "new_per_run"
            else (dispatch_session_id or f"cron:{job.id}")
        )
        dispatch_meta: Dict[str, Any] = {
            **dict(job.dispatch.meta or {}),
            "execution_session_id": execution_session_id,
            "dispatch_session_id": dispatch_session_id,
            "session_mode": session_mode,
        }
        logger.info(
            "cron execute: job_id=%s channel=%s task_type=%s "
            "target_user_id=%s dispatch_session_id=%s "
            "execution_session_id=%s session_mode=%s",
            job.id,
            job.dispatch.channel,
            job.task_type,
            target_user_id[:40] if target_user_id else "",
            dispatch_session_id[:40] if dispatch_session_id else "",
            execution_session_id[:40] if execution_session_id else "",
            session_mode,
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
                session_id=dispatch_session_id,
                text=job.text.strip(),
                meta=dispatch_meta,
            )
            return

        # agent: run request as the dispatch target user so context matches
        logger.info(
            "cron agent: job_id=%s channel=%s stream_query then send_event",
            job.id,
            job.dispatch.channel,
        )
        assert job.request is not None
        req: Dict[str, Any] = job.request.model_dump(mode="json")
        req["user_id"] = target_user_id or "cron"
        req["session_id"] = execution_session_id

        async def _run() -> None:
            async for event in self._runner.stream_query(req):
                await self._channel_manager.send_event(
                    channel=job.dispatch.channel,
                    user_id=target_user_id,
                    session_id=dispatch_session_id,
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
