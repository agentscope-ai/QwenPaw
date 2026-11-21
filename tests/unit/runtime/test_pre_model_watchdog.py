# -*- coding: utf-8 -*-
"""Tests for the pre-model stall watchdog in ``Runtime.run``."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.exceptions import AgentPreModelStallError
from qwenpaw.runtime.hooks import HookResult
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import (
    AgentRequest,
    Message,
    Role,
    RunStatus,
    TextContent,
)


class _Hooks:
    async def run(self, phase, ctx):  # noqa: ARG002
        return HookResult()


class _Commands:
    async def dispatch(self, text, ctx):  # noqa: ARG002
        return None


class _Agent:
    model = None
    state = SimpleNamespace(context=[])
    toolkit = None

    async def close(self) -> None:
        return None


class _Builder:
    def __init__(self, app_services=None) -> None:  # noqa: ARG002
        pass

    async def build(self, ctx):  # noqa: ARG002
        return _Agent()


class _StallingExecutor:
    def __init__(self, agent, envelope) -> None:  # noqa: ARG002
        pass

    async def run(self, msgs):  # noqa: ARG002
        await asyncio.sleep(60)
        yield  # pragma: no cover


def _workspace() -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="default",
        workspace_dir=Path("."),
        plugins=SimpleNamespace(
            hook_registry=_Hooks(),
            slash_command_registry=_Commands(),
            modes=[],
        ),
    )


@pytest.mark.asyncio
async def test_pre_model_stall_becomes_a_visible_error(monkeypatch) -> None:
    import qwenpaw.runtime.runtime as runtime_module

    monkeypatch.setenv("QWENPAW_AGENT_PRE_MODEL_TIMEOUT", "0.05")
    monkeypatch.setattr(runtime_module, "AgentBuilder", _Builder)
    monkeypatch.setattr(runtime_module, "AgentExecutor", _StallingExecutor)

    request = AgentRequest(
        session_id="session-1",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="hello")],
            ),
        ],
    )
    runtime = Runtime(workspace=_workspace(), app_services=None)

    events = []
    with pytest.raises(AgentPreModelStallError):
        async for event in runtime.run(request):
            events.append(event)

    failed = [
        event
        for event in events
        if getattr(event, "status", None) == RunStatus.Failed
    ]
    assert failed, "the watchdog must emit a terminal failed response"
    assert failed[-1].error["code"] == "AGENT_PRE_MODEL_STALL"
    assert "produced no response" in failed[-1].error["message"]


@pytest.mark.asyncio
async def test_first_heartbeat_does_not_disarm_the_watchdog(
    monkeypatch,
) -> None:
    import qwenpaw.runtime.runtime as runtime_module

    class _HeartbeatThenStallExecutor:
        def __init__(self, agent, envelope) -> None:  # noqa: ARG002
            pass

        async def run(self, msgs):  # noqa: ARG002
            from qwenpaw.schemas import Event

            yield Event(object="message", type="heartbeat")
            await asyncio.sleep(60)

    monkeypatch.setenv("QWENPAW_AGENT_PRE_MODEL_TIMEOUT", "0.05")
    monkeypatch.setattr(runtime_module, "AgentBuilder", _Builder)
    monkeypatch.setattr(
        runtime_module,
        "AgentExecutor",
        _HeartbeatThenStallExecutor,
    )

    request = AgentRequest(
        session_id="session-2",
        input=[
            Message(
                role=Role.USER,
                content=[TextContent(text="hello")],
            ),
        ],
    )
    runtime = Runtime(workspace=_workspace(), app_services=None)

    with pytest.raises(AgentPreModelStallError):
        async for _ in runtime.run(request):
            pass
