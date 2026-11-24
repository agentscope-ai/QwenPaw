# -*- coding: utf-8 -*-
"""Approval notifications must reach the chat channel that raised them.

#6695 / #6819 reported that approvals raised from a chat turn (WeChat in
particular) were unreachable there: the console showed a dialog, the chat
channel showed nothing, and the request expired after the timeout.

Root cause: ``ApprovalService`` routes notifications through
``extra["_channel_instance"]``, and that field was only attached on the
console SSE path (``BaseChannel._stream_with_tracker``).  Chat turns run
through ``_run_process_loop``, where it stayed unset.

These tests pin the four pieces of the fix:

* ``_run_process_loop`` attaches the channel instance to the request;
* approval bodies carry copy-paste commands with the *full* request id;
* a notification opts out of the channel's message-merge window; and
* a timeout is reported instead of expiring silently.

Since #8187 the WeChat channel ships as a plugin behind
``IsolatedChannelProxy``, so the merge-window assertion targets the host
proxy's text-merge buffer rather than a removed ``wechat/channel.py``.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import contextvars
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.approvals.models import ApprovalRequestSummary
from qwenpaw.app.approvals.service import ApprovalService
from qwenpaw.app.channels.base import BaseChannel
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.channel_protocol.models import TEXT_MERGE_CAPABILITY
from qwenpaw.channel_protocol.response_policy import ResponsePolicy
from qwenpaw.security.tool_guard.approval import (
    ApprovalDecision,
    format_approval_actions,
    format_channel_approval_body,
    format_summary_approval_body,
    short_request_id,
)
from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)

REQUEST_ID = "5b7e1f12-64be-40aa-9a46-2a1f0c7d9e11"
SHORT_ID = REQUEST_ID[:16]


def _tool_guard_result() -> ToolGuardResult:
    return ToolGuardResult(
        tool_name="Bash",
        params={"command": "rm -rf build/"},
        findings=[
            GuardFinding(
                id="f1",
                rule_id="destructive_command",
                category=GuardThreatCategory.COMMAND_INJECTION,
                severity=GuardSeverity.HIGH,
                title="Destructive command",
                description="Command removes files recursively",
                tool_name="Bash",
            ),
        ],
    )


def _bare_channel() -> BaseChannel:
    """A BaseChannel without transport: only notification plumbing matters."""
    channel = object.__new__(BaseChannel)
    channel.enabled = True
    channel._on_reply_sent = None
    return channel


# ---------------------------------------------------------------------------
# Actionable bodies
# ---------------------------------------------------------------------------


def test_actions_carry_the_full_request_id() -> None:
    """The service resolves exact ids; a 16-char prefix is not found."""
    text = "\n".join(format_approval_actions(REQUEST_ID))
    assert f"/approval approve {REQUEST_ID}" in text
    assert f"/approval deny {REQUEST_ID}" in text
    assert f"/approval cancel {REQUEST_ID}" in text
    # A copy-paste of the truncated id must not be offered as a command.
    assert f"/approval approve {SHORT_ID}`" not in text
    assert "/approval list" in text


def test_actions_use_the_short_id_for_display_only() -> None:
    lines = format_approval_actions(REQUEST_ID)
    display = [line for line in lines if "/approval " not in line]
    assert any(SHORT_ID in line for line in display)
    assert not any(REQUEST_ID in line for line in display)


def test_actions_without_request_id_stay_usable() -> None:
    text = "\n".join(format_approval_actions())
    assert "/approval approve" in text
    assert SHORT_ID not in text


def test_short_request_id_is_a_prefix() -> None:
    assert short_request_id(REQUEST_ID) == SHORT_ID
    assert short_request_id(None) == ""


def test_tool_guard_body_carries_actions_with_full_id() -> None:
    body = format_channel_approval_body(
        _tool_guard_result(),
        request_id=REQUEST_ID,
    )
    assert "**Tool**: `Bash`" in body
    assert f"/approval approve {REQUEST_ID}" in body


def test_driver_style_summary_body_is_actionable() -> None:
    """Driver approvals used to push a bare sentence with no way to answer."""
    summary = ApprovalRequestSummary(
        source_type="driver_policy",
        name="driver:mcp:blender",
        severity="medium",
        result_summary="Driver 'mcp:blender' requires approval for call.",
    )
    body = format_summary_approval_body(summary, request_id=REQUEST_ID)
    assert "driver:mcp:blender" in body
    assert "requires approval for call" in body
    assert f"/approval approve {REQUEST_ID}" in body


# ---------------------------------------------------------------------------
# Service notification payloads
# ---------------------------------------------------------------------------


def _service() -> ApprovalService:
    svc = ApprovalService()
    svc._notify_channel = AsyncMock()  # type: ignore[method-assign]
    return svc


@pytest.mark.asyncio
async def test_summary_pending_notifies_with_actionable_body() -> None:
    svc = _service()
    pending = await svc.create_pending_summary(
        session_id="wechat:s1",
        root_session_id="wechat:s1",
        owner_agent_id="default",
        user_id="u1",
        channel="wechat",
        agent_id="default",
        summary=ApprovalRequestSummary(
            source_type="driver_policy",
            name="driver:mcp:blender",
            severity="medium",
            result_summary="Driver 'mcp:blender' requires approval for call.",
        ),
        extra={"_channel_instance": object()},
    )
    await asyncio.sleep(0)  # let the fire-and-forget notify task run

    svc._notify_channel.assert_awaited_once()
    _pending, body = svc._notify_channel.await_args.args
    assert f"/approval approve {pending.request_id}" in body
    assert "driver:mcp:blender" in body


@pytest.mark.asyncio
async def test_timeout_is_reported_instead_of_being_silent() -> None:
    svc = _service()
    pending = await svc.create_pending_summary(
        session_id="wechat:s1",
        root_session_id="wechat:s1",
        owner_agent_id="default",
        user_id="u1",
        channel="wechat",
        agent_id="default",
        summary=ApprovalRequestSummary(
            source_type="driver_policy",
            name="driver:mcp:blender",
        ),
        timeout_seconds=0.01,
        extra={"_channel_instance": object()},
    )
    decision = await svc.wait_for_approval(pending, 0.01)

    assert decision == ApprovalDecision.TIMEOUT
    kinds = [
        c.kwargs.get("message_type")
        for c in svc._notify_channel.await_args_list
    ]
    assert "approval_timeout" in kinds


@pytest.mark.asyncio
async def test_console_channel_is_not_notified() -> None:
    svc = _service()
    await svc.create_pending_summary(
        session_id="s1",
        root_session_id="s1",
        owner_agent_id="default",
        user_id="u1",
        channel="console",
        agent_id="default",
        summary=ApprovalRequestSummary(
            source_type="driver_policy",
            name="driver:mcp:blender",
        ),
        extra={"_channel_instance": object()},
    )
    await asyncio.sleep(0)
    svc._notify_channel.assert_not_awaited()


# ---------------------------------------------------------------------------
# Channel instance plumbing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_process_loop_attaches_channel_instance() -> None:
    channel = _bare_channel()

    async def _process(_request: object):
        if _request is None:  # pragma: no cover - keeps an async generator
            yield None

    channel._process = _process
    channel._clear_session_turn_usage = MagicMock()
    channel._on_process_completed = AsyncMock()
    channel._commit_turn_usage = AsyncMock()
    channel._finish_response_cycle = AsyncMock()

    request = SimpleNamespace(session_id="wechat:s1")
    await channel._run_process_loop(request, "to-user", {})

    assert request.channel_instance is channel


# ---------------------------------------------------------------------------
# Merge window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_notification_marks_the_send_no_merge() -> None:
    channel = _bare_channel()
    channel.on_event_message_completed = AsyncMock()

    await channel.send_approval_notification(
        session_id="wechat:s1",
        user_id="u1",
        request_id=REQUEST_ID,
        tool_name="Bash",
        severity="high",
        result_summary="Approval Required",
        message_type="approval_timeout",
    )

    (
        _request,
        _handle,
        event,
        meta,
    ) = channel.on_event_message_completed.await_args.args
    assert meta["no_merge"] is True
    assert event.metadata["metadata"]["message_type"] == "approval_timeout"


def _proxy() -> IsolatedChannelProxy:
    proxy = object.__new__(IsolatedChannelProxy)
    proxy.enabled = True
    proxy.descriptor = SimpleNamespace(
        capabilities=(TEXT_MERGE_CAPABILITY,),
    )
    proxy._response_context = contextvars.ContextVar(
        "test_response",
        default=None,
    )

    async def _route(_to_handle, _meta):
        return "route-1"

    async def _response_policy(_to_handle, _meta):
        return ResponsePolicy(text_merge_delay_ms=30_000)

    proxy._route = _route
    proxy._response_policy = _response_policy
    proxy._buffer_response_text = AsyncMock(return_value=None)
    proxy._flush_response_text = AsyncMock(return_value=None)
    proxy._send_operation_immediate = AsyncMock(return_value="sent")
    return proxy


async def _send_text(proxy: IsolatedChannelProxy, meta: dict) -> str | None:
    return await proxy._send_operation_owned(
        "wechat:reply:1",
        meta,
        "message.create",
        content_source="content_parts",
        content_parts=[{"type": "text", "text": "Approval Required"}],
    )


@pytest.mark.asyncio
async def test_no_merge_bypasses_the_text_merge_buffer() -> None:
    proxy = _proxy()

    result = await _send_text(proxy, {"no_merge": True})

    assert result == "sent"
    proxy._buffer_response_text.assert_not_awaited()
    proxy._flush_response_text.assert_awaited_once_with("route-1")
    proxy._send_operation_immediate.assert_awaited_once()


@pytest.mark.asyncio
async def test_merge_still_buffers_without_the_flag() -> None:
    proxy = _proxy()

    await _send_text(proxy, {})

    proxy._buffer_response_text.assert_awaited_once()
    proxy._send_operation_immediate.assert_not_awaited()
