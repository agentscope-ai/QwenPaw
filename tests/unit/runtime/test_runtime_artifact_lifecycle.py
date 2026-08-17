# -*- coding: utf-8 -*-
"""Runtime artifact lifecycle ordering."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from agentscope.event import EventType
from agentscope.message import Msg, TextBlock
import pytest

import qwenpaw.runtime.runtime as runtime_module
from qwenpaw.agents.artifacts.context import register_current_artifact
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.hooks.session.session_hook import SessionSaveHook
from qwenpaw.hooks.workspace_artifacts_hook import (
    WorkspaceArtifactsCleanupHook,
    WorkspaceArtifactsFinalizeHook,
    WorkspaceArtifactsHook,
)
from qwenpaw.runtime.hooks import (
    HookAction,
    HookBase,
    HookRegistry,
    HookResult,
)
from qwenpaw.runtime.phases import Phase
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import AgentRequest, MessageType, RunStatus


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
        if phase == Phase.FINALIZE_TURN:
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
        if phase == Phase.FINALIZE_TURN:
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


class _CancellationAgent:
    name = "assistant"

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.state = SimpleNamespace(context=[])

    def state_dict(self) -> dict:
        return {"saved": True}

    async def close(self) -> None:
        return None


class _CancellationBuilder:
    output_path: Path

    def __init__(self, **_kwargs) -> None:
        pass

    async def build(self, _ctx) -> _CancellationAgent:
        return _CancellationAgent(self.output_path)


class _CancellingFileExecutor:
    def __init__(self, agent, _envelope) -> None:
        self.agent = agent

    async def run(self, input_msgs):
        del input_msgs
        self.agent.output_path.write_text("partial", encoding="utf-8")
        if not register_current_artifact(self.agent.output_path):
            yield None
            return
        raise asyncio.CancelledError


class _FinalizeCounterHook(HookBase):
    name = "finalize_counter"
    phase = Phase.FINALIZE_TURN
    priority = 70

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _ctx) -> HookResult:
        self.calls += 1
        return HookResult()


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
        Phase.FINALIZE_TURN,
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


async def test_cancelled_turn_emits_and_persists_written_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "partial.txt"
    _CancellationBuilder.output_path = output_path
    monkeypatch.setattr(runtime_module, "AgentBuilder", _CancellationBuilder)
    monkeypatch.setattr(
        runtime_module,
        "AgentExecutor",
        _CancellingFileExecutor,
    )
    counter = _FinalizeCounterHook()
    hooks = HookRegistry()
    for hook in (
        WorkspaceArtifactsHook(),
        counter,
        WorkspaceArtifactsFinalizeHook(),
        SessionSaveHook(),
        WorkspaceArtifactsCleanupHook(),
    ):
        hooks.register(hook)
    session = SafeJSONSession(str(tmp_path / "sessions"))
    workspace = SimpleNamespace(
        plugins=SimpleNamespace(
            hook_registry=hooks,
            slash_command_registry=_NoSlashDispatch(),
            modes=[],
        ),
        workspace_dir=tmp_path,
        agent_id="agent-1",
        session=session,
    )
    runtime = Runtime(workspace=workspace, app_services=None)
    request = AgentRequest(
        input=[],
        session_id="chat-1",
        user_id="user-1",
    )
    events = []

    with pytest.raises(asyncio.CancelledError):
        async for event in runtime.run(request):
            events.append(event)

    assert counter.calls == 1
    terminal_index = max(
        index
        for index, event in enumerate(events)
        if event.object == "response" and event.status == RunStatus.Completed
    )
    artifact_indexes = [
        index
        for index, event in enumerate(events)
        if getattr(event, "type", None)
        in {MessageType.PLUGIN_CALL, MessageType.PLUGIN_CALL_OUTPUT}
    ]
    assert artifact_indexes == [terminal_index - 2, terminal_index - 1]

    persisted = await session.get_session_state_dict(
        "chat-1",
        "user-1",
    )
    agent_state = persisted["agent"]
    manifest = agent_state["workspace_artifact_manifests"][0]
    artifact = manifest["artifacts"][0]
    assert artifact["path"] == "partial.txt"
    assert manifest["version"] == 3
    assert agent_state["workspace_artifact_roots"][artifact["root_ref"]] == {
        "root": "workspace",
        "path": str(tmp_path.resolve()),
    }
