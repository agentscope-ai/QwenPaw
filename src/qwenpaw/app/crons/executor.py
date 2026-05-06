# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict

from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

from ..channels.renderer import MessageRenderer
from ..inbox_trace_store import (
    append_trace_event,
    create_trace,
    finalize_trace,
)
from .models import CronJobSpec

logger = logging.getLogger(__name__)


class CronExecutor:
    def __init__(self, *, runner: Any, channel_manager: Any):
        self._runner = runner
        self._channel_manager = channel_manager
        self._renderer = MessageRenderer()

    def _extract_push_preview(self, event: Any) -> str | None:
        if (
            getattr(event, "object", None) != "message"
            or getattr(event, "status", None) != RunStatus.Completed
        ):
            return None
        msg_type = str(getattr(event, "type", "") or "").lower()
        # Keep tool/thinking events as structured trace entries instead of
        # flattening them into assistant preview text.
        if (
            "reasoning" in msg_type
            or "thinking" in msg_type
            or "function_call" in msg_type
            or "plugin_call" in msg_type
            or "mcp_tool_call" in msg_type
        ):
            return None
        parts = self._renderer.message_to_parts(event)
        body = self._renderer.parts_to_text(parts).strip()
        return body or None

    def _extract_structured_trace_event(
        self,
        event: Any,
    ) -> dict[str, Any] | None:
        obj = getattr(event, "object", None)
        status = getattr(event, "status", None)
        if status != RunStatus.Completed:
            return None

        if obj == "message":
            msg_type = str(getattr(event, "type", "") or "").lower()
            parts = self._renderer.message_to_parts(event)
            text_preview = self._renderer.parts_to_text(parts).strip()
            tool_name = self._extract_tool_name(event)
            if "reasoning" in msg_type or "thinking" in msg_type:
                return {
                    "kind": "thinking",
                    "message_type": msg_type or "reasoning",
                    "text": text_preview,
                }
            if (
                "function_call" in msg_type
                or "plugin_call" in msg_type
                or "mcp_tool_call" in msg_type
            ):
                kind = "tool_output" if "output" in msg_type else "tool_call"
                tool_payload_fields = self._extract_tool_payload_fields(event)
                trace_event = {
                    "kind": kind,
                    "message_type": msg_type,
                    "text": text_preview,
                }
                if tool_name:
                    trace_event["tool_name"] = tool_name
                trace_event.update(tool_payload_fields)
                return trace_event
            return None

        if obj == "response":
            return {
                "kind": "response_completed",
                "status": str(status),
            }
        return None

    def _extract_tool_name(self, event: Any) -> str | None:
        content = getattr(event, "content", None) or []
        for item in content:
            data = getattr(item, "data", None)
            if isinstance(data, dict):
                name = data.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
        return None

    def _extract_tool_payload_fields(self, event: Any) -> dict[str, str]:
        content = getattr(event, "content", None) or []
        for item in content:
            data = getattr(item, "data", None)
            if not isinstance(data, dict):
                continue
            payload: dict[str, str] = {}
            arguments = data.get("arguments")
            output = data.get("output")
            if isinstance(arguments, str) and arguments.strip():
                payload["tool_input"] = arguments
            elif arguments is not None:
                try:
                    payload["tool_input"] = json.dumps(
                        arguments,
                        ensure_ascii=False,
                        indent=2,
                    )
                except Exception:  # pylint: disable=broad-except
                    payload["tool_input"] = str(arguments)
            if isinstance(output, str) and output.strip():
                payload["tool_output"] = output
            elif output is not None:
                try:
                    payload["tool_output"] = json.dumps(
                        output,
                        ensure_ascii=False,
                        indent=2,
                    )
                except Exception:  # pylint: disable=broad-except
                    payload["tool_output"] = str(output)
            if payload:
                return payload
        return {}

    async def _append_trace_events(self, run_id: str, event: Any) -> None:
        structured_trace_event = self._extract_structured_trace_event(event)
        if structured_trace_event is not None:
            await append_trace_event(run_id, structured_trace_event)
        preview = self._extract_push_preview(event)
        if preview:
            await append_trace_event(
                run_id,
                {
                    "kind": "push_preview",
                    "text": preview,
                },
            )

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
            # TODO: text type需要这么多额外的meta信息吗？
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

        # Determine session_id based on share_session
        share_session = job.runtime.share_session
        if share_session:
            req["session_id"] = target_session_id or f"cron:{job.id}"
        else:
            req["session_id"] = (
                f"{target_session_id}:cron:{job.id}"
                if target_session_id
                else f"cron:{job.id}"
            )
        run_id = str(uuid.uuid4())
        delivery_error: str | None = None
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
            async for event in self._runner.stream_query(req):
                await self._append_trace_events(run_id, event)
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
            await finalize_trace(
                run_id,
                status="timeout",
                error=f"timed out after {job.runtime.timeout_seconds}s",
            )
            raise
        except asyncio.CancelledError:
            logger.info("cron execute: job_id=%s cancelled", job.id)
            await finalize_trace(
                run_id,
                status="cancelled",
                error="execution cancelled",
            )
            raise
        except Exception as e:  # pylint: disable=broad-except
            await finalize_trace(
                run_id,
                status="error",
                error=repr(e),
            )
            raise
