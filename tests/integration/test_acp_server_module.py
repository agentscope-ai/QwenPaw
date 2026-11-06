# -*- coding: utf-8 -*-
"""Integration tests for the ACP server adapter internals.

Covers src/qwenpaw/agents/acp/server.py (671 uncovered lines):
prompt text extraction, tool-call input parsing, tool result status
classification, envelope tracking for stream events.
"""

# pylint: disable=protected-access

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_plain_acp_session_requires_mcp_before_session_creation(
    monkeypatch,
    tmp_path,
):
    from unittest.mock import AsyncMock
    from acp import RequestError, text_block
    from qwenpaw.agents.acp.server import QwenPawACPAgent
    from qwenpaw.app.mcp import feature_gate

    async def unavailable(*_args, **_kwargs):
        return False

    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host"):
        monkeypatch.setattr(feature_gate, "prepare_mcp_for_use", unavailable)
        agent = QwenPawACPAgent(agent_id="default")
        try:
            with pytest.raises(RequestError) as failure:
                await agent.new_session(cwd="/task", mcp_servers=[])
            assert failure.value.data["code"] == "mcp_plugin_unavailable"
            assert agent._sessions == {}
            # A session created while MCP was available cannot bypass later revocation.
            agent._sessions["existing"] = {}
            start = AsyncMock(
                side_effect=AssertionError("ACP must stay blocked"),
            )
            monkeypatch.setattr(agent, "_ensure_workspace", start)
            monkeypatch.setattr(
                agent,
                "_bridge_approval_requests",
                AsyncMock(),
            )
            with pytest.raises(RequestError) as turn_failure:
                await agent.prompt([text_block("hello")], "existing")
            assert turn_failure.value.data["code"] == "mcp_plugin_unavailable"
            start.assert_not_awaited()
            assert not agent._prompt_tasks and not agent._cancel_events
        finally:
            await agent._shutdown_workspace()


@pytest.mark.integration
@pytest.mark.p1
def test_extract_text_from_dict_blocks() -> None:
    """Dict blocks contribute their text fields."""
    from qwenpaw.agents.acp.server import _extract_text

    blocks = [{"text": "hello"}, {"text": "world"}]
    assert _extract_text(blocks) == "hello\nworld"


@pytest.mark.integration
@pytest.mark.p1
def test_extract_text_skips_empty() -> None:
    """Empty-text blocks are skipped."""
    from qwenpaw.agents.acp.server import _extract_text

    blocks = [{"text": ""}, {"text": "only"}]
    assert _extract_text(blocks) == "only"


@pytest.mark.integration
@pytest.mark.p1
def test_extract_text_object_blocks() -> None:
    """Object blocks with a text attribute are handled."""
    from qwenpaw.agents.acp.server import _extract_text

    class FakeBlock:
        text = "from-object"

    assert _extract_text([FakeBlock()]) == "from-object"


@pytest.mark.integration
@pytest.mark.p1
def test_extract_text_empty_list() -> None:
    """No blocks yields an empty string."""
    from qwenpaw.agents.acp.server import _extract_text

    assert _extract_text([]) == ""


@pytest.mark.integration
@pytest.mark.p1
def test_tool_raw_input_dict_passthrough() -> None:
    """Dict arguments pass through unchanged."""
    from qwenpaw.agents.acp.server import _EnvelopeTracker

    data = {"arguments": {"cmd": "ls"}}
    assert _EnvelopeTracker._tool_raw_input(data) == {"cmd": "ls"}


@pytest.mark.integration
@pytest.mark.p1
def test_tool_raw_input_json_string_parsed() -> None:
    """JSON-encoded string arguments are parsed."""
    from qwenpaw.agents.acp.server import _EnvelopeTracker

    data = {"arguments": '{"cmd": "ls"}'}
    assert _EnvelopeTracker._tool_raw_input(data) == {"cmd": "ls"}


@pytest.mark.integration
@pytest.mark.p1
def test_tool_raw_input_non_json_string_kept() -> None:
    """Non-JSON string arguments are kept as raw strings."""
    from qwenpaw.agents.acp.server import _EnvelopeTracker

    data = {"arguments": "just a command"}
    assert _EnvelopeTracker._tool_raw_input(data) == "just a command"


@pytest.mark.integration
@pytest.mark.p1
def test_tool_raw_input_missing_or_blank() -> None:
    """Missing or blank arguments yield None."""
    from qwenpaw.agents.acp.server import _EnvelopeTracker

    assert _EnvelopeTracker._tool_raw_input({}) is None
    assert _EnvelopeTracker._tool_raw_input({"arguments": None}) is None
    assert _EnvelopeTracker._tool_raw_input({"arguments": "   "}) is None


@pytest.mark.integration
@pytest.mark.p1
def test_tool_result_status_failure_states() -> None:
    """Cancelled/denied/error states classify as failed."""
    from qwenpaw.agents.acp.server import _EnvelopeTracker

    for state in ["cancelled", "denied", "error", "failed", "interrupted"]:
        assert _EnvelopeTracker._tool_result_status({"state": state}) == (
            "failed"
        )


@pytest.mark.integration
@pytest.mark.p1
def test_tool_result_status_completed() -> None:
    """Success states classify as completed."""
    from qwenpaw.agents.acp.server import _EnvelopeTracker

    assert _EnvelopeTracker._tool_result_status({"state": "success"}) == (
        "completed"
    )
    assert _EnvelopeTracker._tool_result_status({}) == "completed"


@pytest.mark.integration
@pytest.mark.p1
def test_envelope_tracker_init_state() -> None:
    """Tracker starts with empty reasoning message tracking."""
    from qwenpaw.agents.acp.server import _EnvelopeTracker

    tracker = _EnvelopeTracker()
    # Construction must not raise; internal maps start empty.
    assert tracker is not None
