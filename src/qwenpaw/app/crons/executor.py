# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict

from ..inbox_trace_store import (
    append_trace_from_session_delta,
    create_trace,
    finalize_trace,
    read_session_messages,
)
from .models import CronJobSpec

logger = logging.getLogger(__name__)


class CronExecutor:
    def __init__(self, *, workspace: Any, channel_manager: Any):
        self._workspace = workspace
        self._channel_manager = channel_manager

    # pylint: disable=too-many-statements
    async def execute(self, job: CronJobSpec) -> dict[str, Any]:
        """Execute one job once.

        - task_type text: send fixed text to channel
        - task_type agent: ask agent with prompt, send reply to channel (
            stream_query + send_event)
        """
        target_user_id = job.dispatch.target.user_id
        target_session_id = job.dispatch.target.session_id
        target_channel = job.dispatch.channel
        dispatch_meta: Dict[str, Any] = dict(job.dispatch.meta or {})
        if job.task_type == "agent":
            # Agent cron replies still print to the console channel, but
            # should not raise frontend push bubbles (Inbox remains opt-in).
            dispatch_meta["suppress_console_push"] = True
        logger.info(
            "cron execute: job_id=%s channel=%s task_type=%s "
            "target_user_id=%s target_session_id=%s",
            job.id,
            target_channel,
            job.task_type,
            target_user_id[:40] if target_user_id else "",
            target_session_id[:40] if target_session_id else "",
        )

        if job.task_type == "text" and job.text:
            logger.info(
                "cron send_text: job_id=%s channel=%s len=%s",
                job.id,
                target_channel,
                len(job.text or ""),
            )
            text_delivery_error: str | None = None
            try:
                await self._channel_manager.send_text(
                    channel=target_channel,
                    user_id=target_user_id,
                    session_id=target_session_id,
                    text=job.text.strip(),
                    meta=dispatch_meta,
                )
            except Exception as e:  # pylint: disable=broad-except
                text_delivery_error = repr(e)
                logger.warning(
                    "cron text delivery failed: job_id=%s channel=%s error=%s",
                    job.id,
                    job.dispatch.channel,
                    text_delivery_error,
                )
            return {
                "task_type": "text",
                "run_id": None,
                "final_text": job.text.strip(),
                "delivery_status": (
                    "failed" if text_delivery_error else "success"
                ),
                "delivery_error": text_delivery_error,
            }
        # agent: run request as the dispatch target user so context matches
        logger.info(
            "cron agent: job_id=%s channel=%s stream_query then send_event",
            job.id,
            job.dispatch.channel,
        )
        assert job.request is not None
        req: Dict[str, Any] = job.request.model_dump(mode="json")

        req["channel"] = target_channel
        req["user_id"] = target_user_id or "cron"
        raw_context = req.get("request_context")
        request_context = (
            dict(raw_context) if isinstance(raw_context, dict) else {}
        )
        request_context["source"] = "cron"
        request_context["cron_job_id"] = job.id or ""
        req["request_context"] = request_context

        # Determine session_id based on share_session
        share_session = job.runtime.share_session
        if share_session:
            req["session_id"] = target_session_id or f"cron:{job.id}"
        else:
            # Use job.id (not run_id) so all runs of this job accumulate in the
            # same dedicated session, giving users a complete history.
            req["session_id"] = (
                f"{target_session_id}:cron:{job.id}"
                if target_session_id
                else f"cron:{job.id}"
            )
            req["session_source"] = "cron"

        delivery_error: str | None = None
        baseline_messages = await read_session_messages(
            runner=self._workspace,
            session_id=req["session_id"],
            user_id=req["user_id"],
            channel=target_channel,
        )
        baseline_count = len(baseline_messages)

        run_id = str(uuid.uuid4())
        await create_trace(
            run_id,
            meta={
                "job_id": job.id,
                "job_name": job.name,
                "task_type": "agent",
                "dispatch_channel": job.dispatch.channel,
                "target_user_id": target_user_id,
                "target_session_id": target_session_id,
            },
        )

        async def _run() -> None:
            nonlocal delivery_error
            async for event in self._workspace.stream_query(req):
                try:
                    await self._channel_manager.send_event(
                        channel=target_channel,
                        user_id=target_user_id,
                        session_id=target_session_id,
                        event=event,
                        meta=dispatch_meta,
                    )
                except Exception as e:  # pylint: disable=broad-except
                    if delivery_error is None:
                        delivery_error = repr(e)
                        logger.warning(
                            "cron agent delivery failed: job_id=%s "
                            "channel=%s error=%s",
                            job.id,
                            job.dispatch.channel,
                            delivery_error,
                        )

        try:
            await asyncio.wait_for(
                _run(),
                timeout=job.runtime.timeout_seconds,
            )
            await append_trace_from_session_delta(
                run_id=run_id,
                runner=self._workspace,
                session_id=req["session_id"],
                user_id=req["user_id"],
                channel=target_channel,
                baseline_count=baseline_count,
            )
            await finalize_trace(run_id, status="success")
            return {
                "task_type": "agent",
                "run_id": run_id,
                "delivery_status": "failed" if delivery_error else "success",
                "delivery_error": delivery_error,
            }
        except asyncio.TimeoutError:
            logger.warning(
                "cron execute: job_id=%s timed out after %ss",
                job.id,
                job.runtime.timeout_seconds,
            )
            await append_trace_from_session_delta(
                run_id=run_id,
                runner=self._workspace,
                session_id=req["session_id"],
                user_id=req["user_id"],
                channel=target_channel,
                baseline_count=baseline_count,
            )
            await finalize_trace(
                run_id,
                status="timeout",
                error=f"timed out after {job.runtime.timeout_seconds}s",
            )
            raise
        except asyncio.CancelledError:
            logger.info("cron execute: job_id=%s cancelled", job.id)
            await append_trace_from_session_delta(
                run_id=run_id,
                runner=self._workspace,
                session_id=req["session_id"],
                user_id=req["user_id"],
                channel=target_channel,
                baseline_count=baseline_count,
            )
            await finalize_trace(
                run_id,
                status="cancelled",
                error="execution cancelled",
            )
            raise
        except Exception as e:  # pylint: disable=broad-except
            await append_trace_from_session_delta(
                run_id=run_id,
                runner=self._workspace,
                session_id=req["session_id"],
                user_id=req["user_id"],
                channel=target_channel,
                baseline_count=baseline_count,
            )
            await finalize_trace(
                run_id,
                status="error",
                error=repr(e),
            )
            raise
