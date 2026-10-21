# -*- coding: utf-8 -*-
"""The optional UI prompt must stay scoped to capable Console requests."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PLUGIN_DIR = (
    Path(__file__).resolve().parents[3] / "plugins/bundle/qwenpaw-openui"
)


@pytest.fixture(name="openui")
def openui_factory(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "test_openui_plugin",
        PLUGIN_DIR / "plugin.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Keep backend tests independent of Node/build artifacts.
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/system-prompt.txt").write_text(
        "OpenUI test catalog",
        encoding="utf-8",
    )
    module.__file__ = str(tmp_path / "plugin.py")
    factories = []
    module.plugin.register(
        SimpleNamespace(register_middleware=factories.append),
    )
    return factories[0]


def context(channel="console", capabilities=None, **extra):
    return SimpleNamespace(
        request=SimpleNamespace(
            channel=channel,
            request_context={"ui_capabilities": capabilities, **extra},
        ),
        session_id="session-a",
        root_session_id="session-a",
    )


@pytest.mark.parametrize(
    "capabilities",
    [None, {}, [], "v1", {"openui": "v2"}],
)
def test_no_prompt_without_frontend_capability(openui, capabilities):
    assert openui(context(capabilities=capabilities), None) is None


@pytest.mark.parametrize("channel", ["telegram", "cli", "dingtalk", None])
def test_other_channels_unchanged(openui, channel):
    assert openui(context(channel, {"openui": "v1"}), None) is None


@pytest.mark.parametrize(
    "source",
    ["cron", "heartbeat", "subagent", "portability_adaptation"],
)
def test_automation_unchanged(openui, source):
    assert (
        openui(context(capabilities={"openui": "v1"}, source=source), None)
        is None
    )


def test_child_session_unchanged(openui):
    ctx = context(capabilities={"openui": "v1"})
    ctx.root_session_id = "parent"
    assert openui(ctx, None) is None


@pytest.mark.asyncio
async def test_prompt_is_per_request_idempotent_and_preserves_original(openui):
    ctx = context(capabilities={"openui": "v1"})
    for agent_id in ["first", "second"]:
        ctx.agent_id = agent_id
        middleware = openui(ctx, None)
        result = await middleware.on_system_prompt(
            None,
            "Original instructions",
        )
        assert result == "Original instructions\n\nOpenUI test catalog"
        assert await middleware.on_system_prompt(None, result) == result
    assert ctx.request.request_context == {"ui_capabilities": {"openui": "v1"}}
    assert openui(context(), None) is None
