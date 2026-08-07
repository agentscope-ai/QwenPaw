# -*- coding: utf-8 -*-
"""Runtime artifact lifecycle ordering."""

from __future__ import annotations

from types import SimpleNamespace

from agentscope.event import EventType
from agentscope.message import Msg, TextBlock

import qwenpaw.runtime.runtime as runtime_module
from qwenpaw.runtime.hooks import HookAction, HookResult
from qwenpaw.runtime.phases import Phase
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import AgentRequest, RunStatus


class _ShortCircuitHooks:
    def __init__(self) -> None:
        self.phases: list[Phase] = []

    async def run(self, phase: Phase, ctx) -> HookResult:
        self.phases.append(phase)
        if phase == Phase.PRE_DISPATCH:
            return HookResult(
                action=HookAction.SHORT_CIRCUIT,
                payload=Msg(
                    name="assistant",
                    role="assistant",
                    content=[TextBlock(type="text", text="done")],
                ),
            )
        if phase == Phase.POST_RESPONSE:
            ctx.extras["workspace_artifact_manifest"] = {
                "version": 1,
                "agent_id": "agent-1",
                "chat_id": "chat-1",
                "turn_id": "turn-1",
                "artifacts": [],
                "changes": [],
                "truncated": False,
            }
        return HookResult()


class _UnexpectedSlashDispatch:
    async def dispatch(self, raw_text, ctx):
        del raw_text, ctx
        raise AssertionError("slash dispatch must be skipped")


class _NoSlashDispatch:
    async def dispatch(self, raw_text, ctx):
        del raw_text, ctx
        return None


class _NormalHooks:
    async def run(self, phase: Phase, ctx) -> HookResult:
        if phase == Phase.POST_RESPONSE:
            ctx.extras["workspace_artifact_manifest"] = {
                "version": 2,
                "agent_id": "agent-1",
                "chat_id": "chat-1",
                "turn_id": "turn-1",
                "artifacts": [],
                "changes": [],
                "truncated": False,
            }
        return HookResult()


class _FakeAgent:
    async def close(self) -> None:
        return None


class _StreamingBuilder:
    def __init__(self, **_kwargs) -> None:
        pass

    async def build(self, _ctx) -> _FakeAgent:
        return _FakeAgent()


class _StreamingExecutor:
    def __init__(self, _agent, envelope) -> None:
        self.envelope = envelope

    async def run(self, input_msgs):
        del input_msgs
        events = (
            SimpleNamespace(
                type=EventType.TEXT_BLOCK_START.value,
                block_id="answer",
                metadata={},
            ),
            SimpleNamespace(
                type=EventType.TEXT_BLOCK_DELTA.value,
                block_id="answer",
                delta="done",
                metadata={},
            ),
            SimpleNamespace(
                type=EventType.TEXT_BLOCK_END.value,
                block_id="answer",
                metadata={},
            ),
        )
        for event in events:
            async for output in self.envelope.translate_event(event):
                yield output


async def test_pre_dispatch_short_circuit_uses_common_finalize_tail() -> None:
    hooks = _ShortCircuitHooks()
    plugins = SimpleNamespace(
        hook_registry=hooks,
        slash_command_registry=_UnexpectedSlashDispatch(),
        modes=[],
    )
    workspace = SimpleNamespace(
        plugins=plugins,
        workspace_dir=None,
        agent_id="agent-1",
    )
    runtime = Runtime(workspace=workspace, app_services=None)
    request = AgentRequest(
        input=[],
        session_id="chat-1",
        user_id="user-1",
    )

    events = [event async for event in runtime.run(request)]

    assert hooks.phases == [
        Phase.PRE_DISPATCH,
        Phase.POST_RESPONSE,
        Phase.FINALLY,
    ]
    assert [event.type.value for event in events[-3:-1]] == [
        "plugin_call",
        "plugin_call_output",
    ]
    assert events[-1].object == "response"
    assert events[-1].status == RunStatus.Completed


async def test_streaming_answer_precedes_artifact_pair(
    monkeypatch,
) -> None:
    monkeypatch.setattr(runtime_module, "AgentBuilder", _StreamingBuilder)
    monkeypatch.setattr(runtime_module, "AgentExecutor", _StreamingExecutor)
    plugins = SimpleNamespace(
        hook_registry=_NormalHooks(),
        slash_command_registry=_NoSlashDispatch(),
        modes=[],
    )
    workspace = SimpleNamespace(
        plugins=plugins,
        workspace_dir=None,
        agent_id="agent-1",
    )
    runtime = Runtime(workspace=workspace, app_services=None)
    request = AgentRequest(
        input=[],
        session_id="chat-1",
        user_id="user-1",
    )

    events = [event async for event in runtime.run(request)]

    response = events[-1]
    assert response.object == "response"
    assert response.status == RunStatus.Completed
    assert [item.type.value for item in response.output] == [
        "message",
        "plugin_call",
        "plugin_call_output",
    ]
