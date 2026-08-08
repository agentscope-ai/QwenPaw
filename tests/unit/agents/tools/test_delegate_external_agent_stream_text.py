# -*- coding: utf-8 -*-
"""delegate_external_agent final assistant text: multi-chunk completeness.

When the ACP agent emits more than one ``AgentMessageChunk``, the final
``ToolChunk`` must contain the *complete* accumulated text, not just the last
delta.  This pins the fix in ``_stream_action_responses`` which prefers the
complete ``run_result["event"]`` and falls back to the accumulated streamed
text only when ``finish_prompt()`` yields no event (the notification/response
race).
"""
# pylint: disable=protected-access
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from qwenpaw.agents.acp.client import ACPHostedClient
from qwenpaw.config.config import ACPAgentConfig

# Package ``tools.__init__`` re-exports the tool function under the same name
# as the module, so use importlib to get the real module object.
dea = importlib.import_module("qwenpaw.agents.tools.delegate_external_agent")


def _chunk(text: str):
    from acp import text_block
    from acp.schema import AgentMessageChunk

    return AgentMessageChunk(
        sessionUpdate="agent_message_chunk",
        content=text_block(text),
    )


class _StreamingFakeService:
    """run_turn emits two AgentMessageChunks back-to-back on a real client."""

    def __init__(self, *, finish_event: bool = True) -> None:
        self._finish_event = finish_event

    async def run_turn(
        self,
        *,
        chat_id: str,
        agent: str,
        prompt_blocks: list,
        cwd: str,
        on_message,
        restart: bool = False,
    ) -> dict:
        del chat_id, agent, prompt_blocks, cwd, restart
        config = ACPAgentConfig(
            enabled=True,
            command="test",
            trusted=True,
            tool_parse_mode="call_title",
        )
        client = ACPHostedClient(
            agent_name="fake",
            agent_config=config,
            cwd="/tmp",
        )
        client.start_prompt(on_message=on_message)
        # Two chunks in the same turn, exactly the multi-chunk case.
        await client.session_update(
            session_id="chat",
            update=_chunk("Hello"),
        )
        await client.session_update(
            session_id="chat",
            update=_chunk(" world"),
        )
        if self._finish_event:
            event = await client.finish_prompt()
        else:
            # Simulate the original race: the prompt response resolved
            # before the queued notification tasks ran, so finish_prompt()
            # observes no text yet.
            event = None
        return {"status": "completed", "event": event}


async def _collect_final_text(
    *,
    fake_service: _StreamingFakeService,
    tmp_path: Path,
) -> str:
    chunks = [
        chunk
        async for chunk in dea._stream_action_responses(
            service=fake_service,
            chat_id="chat",
            action_name="start",
            runner_name="fake",
            message_text="go",
            execution_cwd=tmp_path,
        )
    ]
    assert chunks, "expected at least the final assistant response chunk"
    final_chunk = chunks[-1]
    content = getattr(final_chunk, "content", None) or []
    return "".join(str(getattr(block, "text", "") or "") for block in content)


@pytest.mark.asyncio
async def test_multi_chunk_final_text_is_complete(tmp_path: Path):
    """Two chunks must produce full 'Hello world' final text."""
    text = await _collect_final_text(
        fake_service=_StreamingFakeService(finish_event=True),
        tmp_path=tmp_path,
    )
    assert "runner: fake" in text
    assert "[assistant]\nHello world" in text
    assert (
        text.count("[assistant]") == 1
    ), "final text must not duplicate a truncated delta: " + repr(text)


@pytest.mark.asyncio
async def test_streamed_fallback_when_finish_prompt_has_no_event(
    tmp_path: Path,
) -> None:
    """Race fallback: accumulated streamed text survives a None event."""
    text = await _collect_final_text(
        fake_service=_StreamingFakeService(finish_event=False),
        tmp_path=tmp_path,
    )
    assert "runner: fake" in text
    assert "[assistant]\nHello world" in text
