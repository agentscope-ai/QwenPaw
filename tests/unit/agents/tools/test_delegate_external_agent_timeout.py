# -*- coding: utf-8 -*-
"""ACP stream loop respects dynamic kill_deadline / extend."""
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.tool_calls import reset_call_context, set_call_context
from qwenpaw.tool_calls._context import ToolCallContext

# Package ``tools.__init__`` re-exports the tool function under the same name
# as the module, so use importlib to get the real module object.
dea = importlib.import_module("qwenpaw.agents.tools.delegate_external_agent")


def _chunk_text(chunk: object) -> str:
    content = getattr(chunk, "content", None) or []
    parts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


@pytest.mark.asyncio
async def test_acp_stream_extend_kill_survives_past_max_runtime(
    tmp_path: Path,
):
    """Re-read kill_deadline so extend keeps ACP past original max_runtime."""
    release = asyncio.Event()
    started = asyncio.Event()

    async def hang_run(**_kwargs):
        started.set()
        await release.wait()
        return {"text": "ok"}

    loop = asyncio.get_running_loop()
    now = loop.time()
    ctx = ToolCallContext(
        tool_call_id="tc-acp-ext",
        tool_name="delegate_external_agent",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=now,
        offload_deadline=now + 30.0,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    chunks: list[object] = []

    try:
        with (
            patch.object(dea, "_run_action", hang_run),
            patch.object(
                dea,
                "_cancel_running_acp_turn",
                new=AsyncMock(),
            ),
        ):
            stream = dea._stream_action_responses(
                service=MagicMock(),
                chat_id="chat-1",
                action_name="message",
                runner_name="runner-x",
                message_text="hi",
                execution_cwd=tmp_path,
                max_runtime=0.1,
            )

            async def consume() -> None:
                async for chunk in stream:
                    chunks.append(chunk)

            task = asyncio.create_task(consume())
            await started.wait()
            await asyncio.sleep(0.04)
            # Extend past original 0.1s max_runtime.
            ctx.kill_deadline = loop.time() + 2.0
            ctx.deadline_changed_event.set()
            await asyncio.sleep(0.12)
            assert not task.done(), "ACP should still run after extend"
            release.set()
            await asyncio.wait_for(task, timeout=2.0)
    finally:
        reset_call_context(token)

    joined = " ".join(_chunk_text(c) for c in chunks)
    assert "reached the preset max runtime" not in joined


@pytest.mark.asyncio
async def test_acp_stream_no_deadline_skips_max_runtime_interrupt(
    tmp_path: Path,
):
    """Clearing kill_deadline must stop ACP from timing out on max_runtime."""
    release = asyncio.Event()
    started = asyncio.Event()

    async def hang_run(**_kwargs):
        started.set()
        await release.wait()
        return {"text": "ok"}

    loop = asyncio.get_running_loop()
    now = loop.time()
    ctx = ToolCallContext(
        tool_call_id="tc-acp-nodeadline",
        tool_name="delegate_external_agent",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=now,
        offload_deadline=now + 30.0,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)

    try:
        with (
            patch.object(dea, "_run_action", hang_run),
            patch.object(
                dea,
                "_cancel_running_acp_turn",
                new=AsyncMock(),
            ),
        ):
            stream = dea._stream_action_responses(
                service=MagicMock(),
                chat_id="chat-2",
                action_name="message",
                runner_name="runner-y",
                message_text="hi",
                execution_cwd=tmp_path,
                max_runtime=0.08,
            )

            async def consume() -> None:
                async for _chunk in stream:
                    pass

            task = asyncio.create_task(consume())
            await started.wait()
            await asyncio.sleep(0.02)
            ctx.kill_deadline = None
            ctx.deadline_changed_event.set()
            await asyncio.sleep(0.12)
            assert not task.done()
            release.set()
            await asyncio.wait_for(task, timeout=2.0)
    finally:
        reset_call_context(token)
