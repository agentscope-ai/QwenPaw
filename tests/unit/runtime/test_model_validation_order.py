# -*- coding: utf-8 -*-
"""Regression tests for model validation after slash-command dispatch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.runtime import runtime as runtime_module
from qwenpaw.exceptions import ConfigurationException
from qwenpaw.runtime.hooks import HookResult
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.runtime.configuration import is_config_independent_command
from qwenpaw.runtime.slash_command_registry import (
    CommandSpec,
    SlashCommandRegistry,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/model", True),
        ("/model help", True),
        ("/model info openai:gpt-4", True),
        ("/model openai:gpt-4", False),
        ("hello", False),
    ],
)
def test_config_independent_model_command_classification(
    text,
    expected,
) -> None:
    """Only read-only model commands bypass agent config loading."""
    request = {
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        ],
    }

    assert is_config_independent_command(request) is expected


@pytest.mark.asyncio
async def test_model_command_runs_before_agent_model_validation(
    monkeypatch,
) -> None:
    """A model-management command must work without building an agent."""
    received_args = []

    async def handle_model(_ctx, args):
        received_args.append(args)
        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text="available models")],
        )

    registry = SlashCommandRegistry()
    registry.register(
        CommandSpec(
            name="model",
            handler=handle_model,
            category="control",
        ),
    )
    hooks = SimpleNamespace(run=AsyncMock(return_value=HookResult()))
    workspace = SimpleNamespace(
        agent_id="default",
        plugins=SimpleNamespace(
            hook_registry=hooks,
            modes=[],
            slash_command_registry=registry,
        ),
        workspace_dir=None,
    )
    builder = MagicMock(side_effect=AssertionError("builder must not run"))
    monkeypatch.setattr(runtime_module, "AgentBuilder", builder)
    runtime = Runtime(
        workspace=workspace,
        app_services=None,
        agent_config=SimpleNamespace(id="default"),
    )

    events = [
        event
        async for event in runtime.run(
            {
                "input": [
                    {
                        "role": "user",
                        "type": "message",
                        "content": [
                            {"type": "text", "text": "/model list"},
                        ],
                    },
                ],
                "session_id": "console:test",
                "user_id": "test",
            },
        )
    ]

    assert received_args == ["list"]
    builder.assert_not_called()
    assert events[-1].object == "response"
    assert events[-1].status.value == "completed"


@pytest.mark.asyncio
async def test_read_only_model_command_runs_when_config_unavailable() -> None:
    """Help/list commands remain usable during a temporary config outage."""
    registry = SlashCommandRegistry()

    async def handle_model(_ctx, args):
        assert args == "help"
        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text="model help")],
        )

    registry.register(
        CommandSpec(
            name="model",
            handler=handle_model,
            category="control",
        ),
    )
    workspace = SimpleNamespace(
        agent_id="default",
        plugins=SimpleNamespace(
            hook_registry=SimpleNamespace(
                run=AsyncMock(return_value=HookResult()),
            ),
            modes=[],
            slash_command_registry=registry,
        ),
        workspace_dir=None,
    )
    runtime = Runtime(
        workspace=workspace,
        app_services=None,
        config_error=ConfigurationException(
            "config offline",
            config_key="agent",
            error_code="AGENT_CONFIG_UNAVAILABLE",
        ),
    )

    events = [
        event
        async for event in runtime.run(
            {
                "input": [
                    {
                        "role": "user",
                        "type": "message",
                        "content": [
                            {"type": "text", "text": "/model help"},
                        ],
                    },
                ],
                "session_id": "console:test",
                "user_id": "test",
            },
        )
    ]

    assert events[-1].object == "response"
    assert events[-1].status.value == "completed"


@pytest.mark.asyncio
async def test_runtime_rejects_request_agent_mismatch() -> None:
    """A request cannot execute with a different workspace agent snapshot."""
    hooks = SimpleNamespace(run=AsyncMock(return_value=HookResult()))
    workspace = SimpleNamespace(
        agent_id="agent-a",
        plugins=SimpleNamespace(
            hook_registry=hooks,
            modes=[],
            slash_command_registry=SlashCommandRegistry(),
        ),
        workspace_dir=None,
    )
    runtime = Runtime(workspace=workspace, app_services=None)

    events = []
    try:
        async for event in runtime.run(
            {
                "agent_id": "agent-b",
                "input": [],
                "session_id": "console:test",
                "user_id": "test",
            },
        ):
            events.append(event)
    except ConfigurationException:
        pass

    assert events[-1].status.value == "failed"
    assert events[-1].error["code"] == "AGENT_ID_MISMATCH"
