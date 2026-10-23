# -*- coding: utf-8 -*-
"""Runtime lifecycle behavior when a streaming consumer closes early."""

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.hooks import HookResult
from qwenpaw.runtime.phases import Phase
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import AgentRequest


class _HookRegistry:
    def __init__(self) -> None:
        self.calls: list[Phase] = []

    async def run(self, phase: Phase, _ctx: object) -> HookResult:
        self.calls.append(phase)
        return HookResult()


class _SlashCommandRegistry:
    async def dispatch(self, _text: str, _ctx: object) -> None:
        return None


class _Agent:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_aclose_is_not_reported_as_runtime_error(monkeypatch) -> None:
    hooks = _HookRegistry()
    agent = _Agent()
    save_calls = 0
    error_envelope_calls = 0
    workspace = SimpleNamespace(
        agent_id="default",
        workspace_dir=None,
        plugins=SimpleNamespace(
            hook_registry=hooks,
            slash_command_registry=_SlashCommandRegistry(),
            modes=[],
        ),
    )

    async def build(_builder: object, _ctx: object) -> _Agent:
        return agent

    async def save_on_cancel(_ctx: object) -> None:
        nonlocal save_calls
        save_calls += 1

    async def error_envelope(_envelope: object, *_args: object):
        nonlocal error_envelope_calls
        error_envelope_calls += 1
        for item in ():
            yield item

    monkeypatch.setattr(
        "qwenpaw.runtime.runtime.AgentBuilder.build",
        build,
    )
    monkeypatch.setattr(
        "qwenpaw.runtime.runtime.Envelope.error_envelope",
        error_envelope,
    )

    runtime = Runtime(workspace=workspace, app_services=None)
    monkeypatch.setattr(runtime, "_try_save_on_cancel", save_on_cancel)
    stream = runtime.run(
        AgentRequest(session_id="session-close"),
    )
    await anext(stream)
    await stream.aclose()

    assert save_calls == 1
    assert error_envelope_calls == 0
    assert Phase.ON_ERROR not in hooks.calls
    assert hooks.calls.count(Phase.FINALLY) == 1
    assert agent.close_calls == 1
