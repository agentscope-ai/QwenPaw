# -*- coding: utf-8 -*-
"""Tests for PromptBuilder and plugin prompt section registration."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from qwenpaw.agents.prompt_builder import PromptBuilder
from qwenpaw.plugins.registry import PluginRegistry


class _FakeAgent:
    """Minimal stand-in providing only what providers may receive."""

    def __init__(self, *, agent_id: str = "datapaw") -> None:
        self._request_context = {"agent_id": agent_id}


@pytest.fixture(autouse=True)
def clean_prompt_sections():
    """Keep singleton registry state isolated for these tests."""
    registry = PluginRegistry()
    for plugin_id in ("test-a", "test-b", "broken-plugin"):
        registry.unregister_plugin(plugin_id)
    yield
    for plugin_id in ("test-a", "test-b", "broken-plugin"):
        registry.unregister_plugin(plugin_id)


def test_builder_orders_sections_after_host_anchor():
    """Plugin sections follow their declared host anchor."""
    registry = PluginRegistry()
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.master",
        after="workspace",
        agent_id="datapaw",
        provider=lambda agent: "MASTER",
    )
    registry.register_prompt_section(
        plugin_id="test-a",
        name="plugin.env",
        after="workspace",
        agent_id="datapaw",
        provider=lambda agent: "ENV",
    )

    builder = PromptBuilder(registry)
    result = builder.build(
        agent=_FakeAgent(),
        agent_id="datapaw",
        workspace="WORKSPACE",
        multimodal="MULTIMODAL",
        env_context="HOST_ENV",
    )

    assert result == (
        "WORKSPACE\n\n" "MASTER\n\n" "ENV\n\n" "MULTIMODAL\n\n" "HOST_ENV"
    )


def test_registry_rejects_invalid_anchor():
    """after must reference a valid host anchor."""
    registry = PluginRegistry()
    with pytest.raises(ValueError, match="must reference a host anchor"):
        registry.register_prompt_section(
            plugin_id="test-a",
            name="plugin.bad",
            after="nonexistent",
            agent_id="datapaw",
            provider=lambda agent: "X",
        )


def test_builder_filters_by_agent_id():
    """agent_id limits which sections appear in the prompt."""
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

    builder = PromptBuilder(registry)

    other = builder.build(
        agent=_FakeAgent(agent_id="other"),
        agent_id="other",
        workspace="WORKSPACE",
    )
    assert other == "WORKSPACE\n\nALL"

    registry.unregister_plugin("test-b")
    datapaw = builder.build(
        agent=_FakeAgent(),
        agent_id="datapaw",
        workspace="WORKSPACE",
    )
    assert datapaw == "WORKSPACE\n\nDATAPAW"


def test_builder_skips_empty_and_failed_providers():
    """Bad or empty providers do not break prompt assembly."""
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

    with patch(
        "qwenpaw.agents.prompt_builder.logger.exception",
    ) as log_exc:
        result = PromptBuilder(registry).build(
            agent=_FakeAgent(),
            agent_id="datapaw",
            workspace="WORKSPACE",
        )

    assert result == "WORKSPACE"
    log_exc.assert_called_once()
