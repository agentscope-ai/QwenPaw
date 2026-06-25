# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the DataPaw spawn_subagent feature toggle."""

from unittest.mock import patch

from plugin_datapaw.constants import DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV


def test_spawn_subagent_default_timeout_is_6000_seconds():
    from plugin_datapaw.core.agents.spawn_subagent import TIMEOUT_SECONDS

    assert TIMEOUT_SECONDS == 6000


def _plan_tool():
    return None


def spawn_subagent():
    return None


class _FakeNotebook:
    def list_tools(self):
        return [_plan_tool]


class _FakeToolkit:
    def __init__(self, include_spawn: bool = True):
        self.tools = {"spawn_subagent": object()} if include_spawn else {}
        self.registered = []
        self.removed = []

    def register_tool_function(self, fn, namesake_strategy="skip"):
        self.registered.append((fn.__name__, namesake_strategy))
        self.tools[fn.__name__] = fn

    def remove_tool_function(self, name):
        self.removed.append(name)
        self.tools.pop(name, None)


def _make_agent(toolkit: _FakeToolkit):
    from plugin_datapaw.core.agents.base import DataPawAgent

    agent = DataPawAgent.__new__(DataPawAgent)
    agent.plan_notebook = _FakeNotebook()
    agent.toolkit = toolkit
    return agent


def test_spawn_subagent_registered_by_default(monkeypatch):
    monkeypatch.delenv(DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV, raising=False)
    toolkit = _FakeToolkit()
    agent = _make_agent(toolkit)

    with patch(
        "plugin_datapaw.core.agents.base.build_spawn_subagent_fn",
        return_value=spawn_subagent,
    ) as build_spawn:
        agent._register_plan_tools()

    build_spawn.assert_called_once_with(agent)
    assert ("_plan_tool", "skip") in toolkit.registered
    assert ("spawn_subagent", "override") in toolkit.registered
    assert toolkit.removed == []


def test_spawn_subagent_disabled_removes_host_tool(monkeypatch):
    monkeypatch.setenv(DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV, "0")
    toolkit = _FakeToolkit()
    agent = _make_agent(toolkit)

    with patch(
        "plugin_datapaw.core.agents.base.build_spawn_subagent_fn",
        side_effect=AssertionError("spawn builder should not be called"),
    ) as build_spawn:
        agent._register_plan_tools()

    build_spawn.assert_not_called()
    assert ("_plan_tool", "skip") in toolkit.registered
    assert toolkit.removed == ["spawn_subagent"]
    assert "spawn_subagent" not in toolkit.tools


def test_master_prompt_includes_subagent_by_default(monkeypatch):
    monkeypatch.delenv(DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV, raising=False)

    from plugin_datapaw.core.agents.base import _read_master_md

    prompt = _read_master_md("zh")

    assert "## Sub-Agent" in prompt
    assert "spawn_subagent(task" in prompt
    assert "DATAPAW_SUBAGENT" not in prompt


def test_master_prompt_hides_subagent_when_disabled(monkeypatch):
    monkeypatch.setenv(DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV, "0")

    from plugin_datapaw.core.agents.base import _read_master_md

    prompt = _read_master_md("zh")

    assert "spawn_subagent" not in prompt
    assert "Sub-Agent" not in prompt
    assert "取数结果与产物落盘" in prompt
