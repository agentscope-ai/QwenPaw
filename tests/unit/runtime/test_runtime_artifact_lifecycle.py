# -*- coding: utf-8 -*-
"""Runtime artifact lifecycle ordering."""

from __future__ import annotations

from types import SimpleNamespace

from agentscope.message import Msg, TextBlock

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
