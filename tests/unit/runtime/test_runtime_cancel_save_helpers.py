# -*- coding: utf-8 -*-
"""Tests for Runtime cancel-save state helpers.

Covers _normalize (dict coercion and session/user id defaults),
_build_context (agent-id priority chain), _close_dangling_tool_calls
(all guard branches and the close-mutation), and
_inject_partial_response (dedup guard and save), using lightweight
fakes for the agent and envelope.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import (
    Msg,
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
)

from qwenpaw.runtime.runtime import Runtime


def _runtime(workspace_agent_id="ws-agent"):
    workspace = SimpleNamespace(
        workspace_dir="/tmp/ws",
        agent_id=workspace_agent_id,
    )
    return Runtime(workspace=workspace, app_services=None)


def _assistant_msg(name: str, content: list) -> Msg:
    return Msg(name=name, role="assistant", content=content)


def _envelope(
    partial: list[tuple[str, str]] | None = None,
    tool_output: dict[str, str] | None = None,
):
    return SimpleNamespace(
        collect_partial_blocks=lambda: list(partial or []),
        collect_tool_output=lambda: dict(tool_output or {}),
    )


def _agent(name="TestAgent", context=None):
    agent = SimpleNamespace(
        name=name,
        state=SimpleNamespace(context=context if context is not None else []),
    )
    agent._save_to_context = lambda blocks: None
    return agent


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_dict_coerced_to_agent_request(self):
        request = Runtime._normalize({"session_id": "s1", "user_id": "u1"})
        from qwenpaw.schemas import AgentRequest

        assert isinstance(request, AgentRequest)
        assert request.session_id == "s1"
        assert request.user_id == "u1"

    def test_missing_session_id_generated(self):
        request = Runtime._normalize({"input": []})
        assert request.session_id
        # user_id falls back to session_id
        assert request.user_id == request.session_id

    def test_existing_request_passthrough(self):
        from qwenpaw.schemas import AgentRequest

        original = AgentRequest(session_id="fixed", user_id="bob")
        result = Runtime._normalize(original)
        assert result is original
        assert result.session_id == "fixed"


# ---------------------------------------------------------------------------
# _build_context agent-id priority
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_request_agent_id_wins(self):
        runtime = _runtime(workspace_agent_id="ws-agent")
        from qwenpaw.schemas import AgentRequest

        request = Runtime._normalize(
            {"session_id": "s1", "agent_id": "body-agent"},
        )
        ctx = runtime._build_context(request)
        assert ctx.agent_id == "body-agent"

    def test_workspace_agent_id_fallback(self):
        runtime = _runtime(workspace_agent_id="ws-agent")
        request = Runtime._normalize({"session_id": "s1"})
        ctx = runtime._build_context(request)
        assert ctx.agent_id == "ws-agent"

    def test_default_when_no_agent_id(self):
        runtime = _runtime(workspace_agent_id=None)
        request = Runtime._normalize({"session_id": "s1"})
        ctx = runtime._build_context(request)
        assert ctx.agent_id == "default"

    def test_root_ids_fall_back_to_session_and_agent(self):
        runtime = _runtime(workspace_agent_id="ws-agent")
        request = Runtime._normalize({"session_id": "s1"})
        ctx = runtime._build_context(request)
        assert ctx.root_session_id == "s1"
        assert ctx.root_agent_id == "ws-agent"


# ---------------------------------------------------------------------------
# _close_dangling_tool_calls
# ---------------------------------------------------------------------------


class TestCloseDanglingToolCalls:
    def test_no_state_returns_zero(self):
        agent = SimpleNamespace(name="a", state=None)
        assert Runtime._close_dangling_tool_calls(agent, _envelope()) == 0

    def test_empty_context_returns_zero(self):
        agent = _agent(context=[])
        assert Runtime._close_dangling_tool_calls(agent, _envelope()) == 0

    def test_last_message_not_assistant_returns_zero(self):
        context = [Msg(name="user", role="user", content=[TextBlock(text="x")])]
        agent = _agent(context=context)
        assert Runtime._close_dangling_tool_calls(agent, _envelope()) == 0

    def test_name_mismatch_returns_zero(self):
        call = ToolCallBlock(id="c1", name="tool", input="{}")
        context = [_assistant_msg("OtherAgent", [call])]
        agent = _agent(name="TestAgent", context=context)
        assert Runtime._close_dangling_tool_calls(agent, _envelope()) == 0

    def test_content_not_list_returns_zero(self):
        # Msg enforces list content, so simulate a raw assistant message
        # whose content is a plain string via a lightweight namespace.
        context = [
            SimpleNamespace(role="assistant", name="TestAgent", content="str"),
        ]
        agent = _agent(context=context)
        assert Runtime._close_dangling_tool_calls(agent, _envelope()) == 0

    def test_matched_call_not_closed(self):
        call = ToolCallBlock(id="c1", name="tool", input="{}")
        result = ToolResultBlock(
            id="c1",
            name="tool",
            state=ToolResultState.SUCCESS,
            output="done",
        )
        context = [_assistant_msg("TestAgent", [call, result])]
        agent = _agent(context=context)
        assert Runtime._close_dangling_tool_calls(agent, _envelope()) == 0
        assert len(context[0].content) == 2

    def test_dangling_call_closed_with_interruption(self):
        call = ToolCallBlock(id="c1", name="tool", input="{}")
        context = [_assistant_msg("TestAgent", [call])]
        agent = _agent(context=context)
        closed = Runtime._close_dangling_tool_calls(agent, _envelope())
        assert closed == 1
        # call marked finished
        assert context[0].content[0].state == ToolCallState.FINISHED
        # result appended
        appended = context[0].content[-1]
        assert isinstance(appended, ToolResultBlock)
        assert appended.id == "c1"
        assert "interrupted" in appended.output

    def test_envelope_output_included_before_interruption(self):
        call = ToolCallBlock(id="c1", name="tool", input="{}")
        context = [_assistant_msg("TestAgent", [call])]
        agent = _agent(context=context)
        closed = Runtime._close_dangling_tool_calls(
            agent,
            _envelope(tool_output={"c1": "partial output"}),
        )
        assert closed == 1
        appended = context[0].content[-1]
        assert appended.output.startswith("partial output")
        assert "interrupted" in appended.output

    def test_multiple_dangling_calls_all_closed(self):
        call1 = ToolCallBlock(id="c1", name="tool", input="{}")
        call2 = ToolCallBlock(id="c2", name="tool", input="{}")
        context = [_assistant_msg("TestAgent", [call1, call2])]
        agent = _agent(context=context)
        closed = Runtime._close_dangling_tool_calls(agent, _envelope())
        assert closed == 2


# ---------------------------------------------------------------------------
# _inject_partial_response
# ---------------------------------------------------------------------------


class TestInjectPartialResponse:
    def test_partial_text_injected(self):
        saved = []
        agent = _agent(context=[])
        agent._save_to_context = saved.extend
        Runtime._inject_partial_response(
            agent,
            _envelope(partial=[("text", "half written")]),
        )
        assert len(saved) == 1
        assert saved[0].type == "text"
        assert saved[0].text == "half written"

    def test_thinking_block_injected(self):
        saved = []
        agent = _agent(context=[])
        agent._save_to_context = saved.extend
        Runtime._inject_partial_response(
            agent,
            _envelope(partial=[("thinking", "reasoning so far")]),
        )
        assert len(saved) == 1
        assert getattr(saved[0], "thinking", "") == "reasoning so far"

    def test_duplicate_text_not_reinjected(self):
        existing_text = "already saved"
        context = [
            _assistant_msg(
                "TestAgent",
                [TextBlock(text=existing_text)],
            ),
        ]
        saved = []
        agent = _agent(context=context)
        agent._save_to_context = saved.extend
        Runtime._inject_partial_response(
            agent,
            _envelope(partial=[("text", existing_text)]),
        )
        assert saved == []

    def test_no_partial_no_save(self):
        saved = []
        agent = _agent(context=[])
        agent._save_to_context = saved.extend
        Runtime._inject_partial_response(agent, _envelope())
        assert saved == []

    def test_envelope_failure_swallowed(self):
        def boom():
            raise RuntimeError("envelope broken")

        envelope = SimpleNamespace(
            collect_partial_blocks=boom,
            collect_tool_output=boom,
        )
        agent = _agent(context=[])
        # must not raise
        Runtime._inject_partial_response(agent, envelope)
