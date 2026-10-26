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
* approval bodies carry copy-paste commands with the short request id;
* a notification bypasses a channel's message-merge window; and
* a timeout is reported instead of expiring silently.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.approvals.models import ApprovalRequestSummary
from qwenpaw.app.approvals.service import ApprovalService
from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.app.channels.wechat.channel import WeChatChannel
from qwenpaw.schemas import ContentType, TextContent
from qwenpaw.security.tool_guard.approval import (
    ApprovalDecision,
    format_approval_actions,
    format_channel_approval_body,
    format_summary_approval_body,
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


def _wechat_channel(tmp_path: Path) -> WeChatChannel:
    media = tmp_path / "media"
    media.mkdir(parents=True, exist_ok=True)
    return WeChatChannel(
        process=MagicMock(),
        enabled=True,
        bot_token="test_token",
        media_dir=str(media),
        display_config=ChannelDisplayConfig(
            show_tool_calls=False,
            show_tool_results=False,
        ),
        dm_policy="open",
        group_policy="open",
    )


# ---------------------------------------------------------------------------
# Actionable bodies
# ---------------------------------------------------------------------------


def test_actions_include_short_request_id() -> None:
    text = "\n".join(format_approval_actions(REQUEST_ID))
    assert f"/approval approve {SHORT_ID}" in text
    assert f"/approval deny {SHORT_ID}" in text
    assert "/approval list" in text


def test_actions_without_request_id_stay_usable() -> None:
    text = "\n".join(format_approval_actions())
    assert "/approval approve" in text
    assert SHORT_ID not in text


def test_tool_guard_body_carries_actions_with_id() -> None:
    body = format_channel_approval_body(
        _tool_guard_result(),
        request_id=REQUEST_ID,
    )
    assert "**Tool**: `Bash`" in body
    assert f"/approval approve {SHORT_ID}" in body


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
    assert f"/approval approve {SHORT_ID}" in body


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
    await svc.create_pending_summary(
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
    assert "/approval approve" in body
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
async def test_run_process_loop_attaches_channel_instance(
    tmp_path: Path,
) -> None:
    channel = _wechat_channel(tmp_path)

    async def _process(_request: object):
        if _request is None:  # pragma: no cover - keeps an async generator
            yield None

    setattr(channel, "_process", _process)
    setattr(channel, "_clear_session_turn_usage", MagicMock())
    setattr(channel, "_on_process_completed", AsyncMock())
    setattr(channel, "_commit_turn_usage", AsyncMock())
    setattr(channel, "_finish_response_cycle", AsyncMock())
    channel._on_reply_sent = None

    request = SimpleNamespace(session_id="wechat:s1")
    await channel._run_process_loop(request, "to-user", {})

    assert request.channel_instance is channel


# ---------------------------------------------------------------------------
# Merge window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wechat_no_merge_bypasses_buffer(tmp_path: Path) -> None:
    channel = _wechat_channel(tmp_path)
    channel._message_merge_enabled = True
    channel._message_merge_delay_ms = 30000
    setattr(channel, "_send_content_parts_immediate", AsyncMock())

    part = TextContent(type=ContentType.TEXT, text="Approval Required")
    await channel.send_content_parts("to-user", [part], {"no_merge": True})

    channel._send_content_parts_immediate.assert_awaited_once()
    assert not channel._merge_buffer


@pytest.mark.asyncio
async def test_wechat_merge_still_buffers_without_the_flag(
    tmp_path: Path,
) -> None:
    channel = _wechat_channel(tmp_path)
    channel._message_merge_enabled = True
    channel._message_merge_delay_ms = 30000
    setattr(channel, "_send_content_parts_immediate", AsyncMock())

    part = TextContent(type=ContentType.TEXT, text="hello")
    await channel.send_content_parts("to-user", [part], {})

    assert channel._merge_buffer, "expected the merge buffer to hold the text"
    channel._send_content_parts_immediate.assert_not_awaited()
