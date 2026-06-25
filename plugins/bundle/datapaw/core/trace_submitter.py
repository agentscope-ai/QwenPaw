# -*- coding: utf-8 -*-
"""Best-effort dialogue trace submission to the CM trace API.

The sender is intentionally narrow: read the already-persisted session
memory, slice the current dialogue, and POST it to CM without ever raising
back into the chat flow.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

import httpx

from qwenpaw.app.inbox_trace_store import flatten_session_messages
from qwenpaw.utils.http import trust_env_for_url

from ..constants import get_datapaw_cm_base_url

_TRACE_SUBMIT_PATH = "/api/v1/trace/submit_trace"
_TIMEOUT_SECONDS = 5.0

logger = logging.getLogger(__name__)


def _cm_trace_url() -> str:
    return f"{get_datapaw_cm_base_url()}{_TRACE_SUBMIT_PATH}"


def _now_timestamp_ms() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _message_id(message: dict[str, Any]) -> str:
    value = message.get("id")
    return str(value) if value is not None else ""


def _message_role(message: dict[str, Any]) -> str:
    value = message.get("role") or message.get("name") or ""
    return str(value).lower()


def _timestamp_sort_key(message: dict[str, Any]) -> tuple[int, Any]:
    value = message.get("timestamp")
    if isinstance(value, str):
        raw = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return (0, datetime.strptime(raw, fmt))
            except ValueError:
                continue
        return (1, raw)
    return (2, "")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if hasattr(value, "dict"):
        return _jsonable(value.dict())
    return {"repr": repr(value)}


def _normalize_messages(
    messages: list[dict[str, Any]],
    *,
    session_id: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        item = dict(message)
        if not _message_id(item):
            item["id"] = f"{session_id}:{index}"
        if not item.get("timestamp"):
            item["timestamp"] = _now_timestamp_ms()
        normalized.append(_jsonable(item))
    return [
        item
        for _, item in sorted(
            enumerate(normalized),
            key=lambda pair: (_timestamp_sort_key(pair[1]), pair[0]),
        )
    ]


def _slice_dialogue_messages(
    messages: list[dict[str, Any]],
    *,
    trigger_msg_id: str = "",
) -> list[dict[str, Any]]:
    """Return the current dialogue, split by the triggering user query."""
    if not messages:
        return []

    start_index: int | None = None
    if trigger_msg_id:
        for idx, message in enumerate(messages):
            if _message_id(message) == trigger_msg_id:
                start_index = idx
                break

    if start_index is None:
        for idx in range(len(messages) - 1, -1, -1):
            if _message_role(messages[idx]) == "user":
                start_index = idx
                break

    if start_index is None:
        start_index = 0
    return messages[start_index:]


def _metadata_string(metadata: dict[str, Any] | None) -> str:
    if not isinstance(metadata, dict):
        metadata = {}
    return json.dumps(_jsonable(metadata), ensure_ascii=False)


def _build_trace_payload(
    *,
    session_id: str,
    user_id: str,
    messages: list[dict[str, Any]],
    request_context: dict[str, Any] | None = None,
    trigger_msg_id: str = "",
) -> dict[str, Any]:
    normalized = _normalize_messages(messages, session_id=session_id)
    dialogue = _slice_dialogue_messages(
        normalized,
        trigger_msg_id=trigger_msg_id,
    )
    payload: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "messages": dialogue,
        "metadata": _metadata_string(request_context),
    }
    return payload


async def submit_trace_from_session(
    *,
    runner: Any,
    session_id: str,
    user_id: str,
    channel: str,
    request_context: dict[str, Any] | None = None,
    trigger_msg_id: str = "",
) -> bool:
    """Submit one dialogue trace to CM. Returns success, never raises."""
    request_id = uuid.uuid4().hex
    url = _cm_trace_url()
    if not session_id or not user_id:
        logger.info(
            "cm trace submit result: session_id=%s success=%s "
            "trace_count=%s message_count=%s reason=%s user_id=%s "
            "request_id=%s",
            session_id,
            False,
            0,
            0,
            "missing_session_or_user",
            user_id,
            request_id,
        )
        return False

    session = getattr(runner, "session", None)
    if session is None:
        logger.info(
            "cm trace submit result: session_id=%s success=%s "
            "trace_count=%s message_count=%s reason=%s request_id=%s",
            session_id,
            False,
            0,
            0,
            "missing_session_store",
            request_id,
        )
        return False

    trace_count = 0
    message_count = 0
    try:
        state = await session.get_session_state_dict(
            session_id,
            user_id,
            channel,
            allow_not_exist=True,
        )
        memory = state.get("agent", {}).get("memory", {})
        messages = flatten_session_messages(memory.get("content"))
        payload = _build_trace_payload(
            session_id=session_id,
            user_id=user_id,
            messages=messages,
            request_context=request_context,
            trigger_msg_id=trigger_msg_id,
        )
        message_count = len(payload["messages"])
        trace_count = 1 if message_count else 0
        if not message_count:
            logger.debug(
                "cm trace submit result: session_id=%s success=%s "
                "trace_count=%s message_count=%s reason=%s request_id=%s",
                session_id,
                False,
                trace_count,
                message_count,
                "no_dialogue_messages",
                request_id,
            )
            return False

        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            trust_env=trust_env_for_url(url),
        ) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"X-Request-Id": request_id},
            )
        if resp.status_code >= 400:
            logger.warning(
                "cm trace submit result: session_id=%s success=%s "
                "trace_count=%s message_count=%s status=%s request_id=%s",
                session_id,
                False,
                trace_count,
                message_count,
                resp.status_code,
                request_id,
            )
            return False

        logger.info(
            "cm trace submit result: session_id=%s success=%s "
            "trace_count=%s message_count=%s status=%s request_id=%s",
            session_id,
            True,
            trace_count,
            message_count,
            resp.status_code,
            request_id,
        )
        return True
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "cm trace submit result: session_id=%s success=%s "
            "trace_count=%s message_count=%s error=%s request_id=%s",
            session_id,
            False,
            trace_count,
            message_count,
            exc,
            request_id,
        )
        return False


def _log_task_exception(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.warning(
            "trace submit task failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def schedule_trace_submit(**kwargs: Any) -> None:
    """Schedule trace submission without blocking the chat response path."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("trace submit skipped: no running event loop")
        return
    task = loop.create_task(submit_trace_from_session(**kwargs))
    task.add_done_callback(_log_task_exception)
