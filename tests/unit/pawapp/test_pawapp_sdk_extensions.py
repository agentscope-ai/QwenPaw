# -*- coding: utf-8 -*-
"""PawApp SDK extension tests: ctx.notify, app.middleware, @app.command."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.pawapp.app import PawApp
from qwenpaw.pawapp.context import PawAppContext


class _WorkspaceRegistry:
    def __init__(self, workspace):
        self._workspace = workspace

    async def get_agent(self, _agent_id):
        return self._workspace


def _make_context(workspace) -> PawAppContext:
    return PawAppContext(
        app_id="qwenpaw-data",
        agent_id="qwenpaw-data",
        channel="console",
        user_id="default",
        _workspace_registry=_WorkspaceRegistry(workspace),
    )


@pytest.mark.asyncio
async def test_notify_delegates_to_channel_manager() -> None:
    channel_manager = SimpleNamespace(send_text=AsyncMock())
    context = _make_context(
        SimpleNamespace(channel_manager=channel_manager),
    )

    await context.notify(
        channels=["dingtalk", "feishu"],
        title="Analysis done",
        body="Report ready",
    )

    assert channel_manager.send_text.await_count == 2
    first = channel_manager.send_text.await_args_list[0].kwargs
    assert first == {
        "channel": "dingtalk",
        "user_id": "default",
        "session_id": "dingtalk:default",
        "text": "Analysis done\nReport ready",
    }


@pytest.mark.asyncio
async def test_notify_honors_explicit_target() -> None:
    channel_manager = SimpleNamespace(send_text=AsyncMock())
    context = _make_context(
        SimpleNamespace(channel_manager=channel_manager),
    )

    await context.notify(
        channels=["telegram"],
        body="ping",
        user_id="alice",
        session_id="telegram:alice",
    )

    kwargs = channel_manager.send_text.await_args.kwargs
    assert kwargs["user_id"] == "alice"
    assert kwargs["session_id"] == "telegram:alice"
    assert kwargs["text"] == "ping"


@pytest.mark.asyncio
async def test_notify_without_channel_manager_is_a_noop() -> None:
    context = _make_context(SimpleNamespace())

    await context.notify(channels=["dingtalk"], title="hello")


@pytest.mark.asyncio
async def test_notify_swallows_per_channel_failures() -> None:
    channel_manager = SimpleNamespace(
        send_text=AsyncMock(side_effect=[KeyError("nope"), None]),
    )
    context = _make_context(
        SimpleNamespace(channel_manager=channel_manager),
    )

    await context.notify(channels=["missing", "console"], body="x")

    assert channel_manager.send_text.await_count == 2


def test_middleware_buffered_and_forwarded_on_register() -> None:
    api = MagicMock()
    app = PawApp("Fixture", app_id="fixture")

    def factory(_ctx, _agent_config):
        return None

    app.middleware(factory, priority=50)
    api.register_middleware.assert_not_called()

    app.register(api)

    api.register_middleware.assert_called_once_with(factory, priority=50)


def test_command_registers_slash_command() -> None:
    api = MagicMock()
    app = PawApp("Fixture", app_id="fixture")

    @app.command("data", description="Toggle data analysis mode")
    async def handler(_ctx, _args):
        return None

    api.register_slash_command.assert_not_called()

    app.register(api)

    api.register_slash_command.assert_called_once_with(
        "data",
        handler,
        category="pawapp:fixture",
        help_text="Toggle data analysis mode",
    )
