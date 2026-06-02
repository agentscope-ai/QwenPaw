# -*- coding: utf-8 -*-
"""Tests for plugin-contributed system prompt sections."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from qwenpaw.plugins.registry import PluginRegistry


class _PromptOnlyAgent:
    """Small stand-in for QwenPawAgent._build_sys_prompt tests."""

    def __init__(
        self,
        *,
        agent_id: str = "datapaw",
        env_context: str | None = None,
    ) -> None:
        self._request_context = {"agent_id": agent_id}
        self._agent_config = SimpleNamespace(heartbeat=None)
        self._workspace_dir = None
        self._language = "zh"
        self.memory_manager = None
        self._env_context = env_context


@pytest.fixture(autouse=True)
def clean_prompt_sections():
    """Keep singleton registry state isolated for these tests."""
    registry = PluginRegistry()
    for plugin_id in ("test-a", "test-b", "broken-plugin"):
        registry.unregister_plugin(plugin_id)
    yield
    for plugin_id in ("test-a", "test-b", "broken-plugin"):
        registry.unregister_plugin(plugin_id)


def test_registry_orders_prompt_sections_linearly_after_host_anchor():
    """Plugin sections under the same host anchor follow registration order."""
    registry = PluginRegistry()
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.master",
        after="profile",
        agent_id="datapaw",
        provider=lambda agent: "MASTER",
    )
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.env",
        after="profile",
        agent_id="datapaw",
        provider=lambda agent: "ENV",
    )

    sections = registry.build_prompt_sections(
        _PromptOnlyAgent(agent_id="datapaw"),
        {
            "workspace": "WORKSPACE",
            "multimodal": "MULTIMODAL",
            "env_context": "HOST_ENV",
        },
    )

    assert [section.name for section in sections] == [
        "workspace",
        "plugin.master",
        "plugin.env",
        "multimodal",
        "env_context",
    ]
    assert [section.content for section in sections] == [
        "WORKSPACE",
        "MASTER",
        "ENV",
        "MULTIMODAL",
        "HOST_ENV",
    ]


def test_registry_rejects_plugin_section_after_anchor():
    """after must reference host anchors, not plugin section names."""
    registry = PluginRegistry()
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.master",
        after="profile",
        agent_id="datapaw",
        provider=lambda agent: "MASTER",
    )

    with pytest.raises(ValueError, match="must reference a host anchor"):
        registry.register_prompt_section(
            plugin_id="test-a",
            name="plugin.env",
            after="plugin.master",
            agent_id="datapaw",
            provider=lambda agent: "ENV",
        )


def test_registry_filters_agent_id_and_unregisters_plugin_sections():
    """agent_id limits sections and unregister_plugin removes them."""
    registry = PluginRegistry()
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.datapaw",
        after="workspace",
        agent_id="datapaw",
        provider=lambda agent: "DATAPAW",
    )
    registry.register_prompt_section(
        plugin_id="test-b",
        name="plugin.all",
        after="workspace",
        agent_id=None,
        provider=lambda agent: "ALL",
    )

    other_sections = registry.build_prompt_sections(
        _PromptOnlyAgent(agent_id="other"),
        {"workspace": "WORKSPACE"},
    )
    assert [section.content for section in other_sections] == [
        "WORKSPACE",
        "ALL",
    ]

    registry.unregister_plugin("test-b")
    datapaw_sections = registry.build_prompt_sections(
        _PromptOnlyAgent(agent_id="datapaw"),
        {"workspace": "WORKSPACE"},
    )
    assert [section.content for section in datapaw_sections] == [
        "WORKSPACE",
        "DATAPAW",
    ]


def test_registry_skips_empty_and_failed_prompt_providers():
    """Bad or empty plugin sections should not break prompt assembly."""
    registry = PluginRegistry()
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.empty",
        after="workspace",
        agent_id="datapaw",
        provider=lambda agent: "",
    )

    def _raise(_agent):
        raise RuntimeError("boom")

    registry.register_prompt_section(
        plugin_id="broken-plugin",
        name="plugin.broken",
        after="workspace",
        agent_id="datapaw",
        provider=_raise,
    )

    with patch("qwenpaw.plugins.registry.logger.exception") as log_exception:
        sections = registry.build_prompt_sections(
            _PromptOnlyAgent(agent_id="datapaw"),
            {"workspace": "WORKSPACE"},
        )

    assert [section.content for section in sections] == ["WORKSPACE"]
    log_exception.assert_called_once()


def test_registry_skips_section_referencing_missing_anchor():
    """Plugin section with missing anchor in host_sections is skipped."""
    registry = PluginRegistry()
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.extra",
        after="env_context",
        agent_id=None,
        provider=lambda agent: "EXTRA",
    )

    sections = registry.build_prompt_sections(
        _PromptOnlyAgent(agent_id="datapaw"),
        {"workspace": "WORKSPACE"},
    )
    assert [s.content for s in sections] == ["WORKSPACE"]


def test_qwenpaw_agent_build_sys_prompt_includes_plugin_sections(monkeypatch):
    """QwenPawAgent._build_sys_prompt consumes registered plugin sections."""
    from qwenpaw.agents import react_agent

    registry = PluginRegistry()
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.master",
        after="workspace",
        agent_id="datapaw",
        provider=lambda agent: "PLUGIN SECTION",
    )
    monkeypatch.setattr(
        react_agent,
        "build_system_prompt_from_working_dir",
        lambda **kwargs: "WORKSPACE",
    )
    monkeypatch.setattr(
        react_agent,
        "build_multimodal_hint",
        lambda: "MULTIMODAL",
    )

    # pylint: disable=protected-access
    prompt = react_agent.QwenPawAgent._build_sys_prompt(
        _PromptOnlyAgent(agent_id="datapaw", env_context="ENV_CONTEXT"),
    )

    assert prompt == (
        "WORKSPACE\n\n" "PLUGIN SECTION\n\n" "MULTIMODAL\n\n" "ENV_CONTEXT"
    )
