# -*- coding: utf-8 -*-
"""Tests for how the plugin seeds its tool into agent configurations."""
# The seeding helper is module-private on purpose; exercising it directly is
# the point of these tests.
# pylint: disable=protected-access

from types import SimpleNamespace

import plugin


def _agent_config(tools=None):
    return SimpleNamespace(tools=tools)


def test_a_missing_entry_is_seeded_enabled():
    agent_config = _agent_config()

    assert plugin._seed_tool_config(agent_config) is True

    tool_config = agent_config.tools.builtin_tools["computer_use"]
    assert tool_config.enabled is True


def test_an_explicitly_disabled_entry_is_respected():
    # The user turned the tool off for this agent; a plugin restart must
    # not silently turn it back on.
    agent_config = _agent_config()
    plugin._seed_tool_config(agent_config)
    agent_config.tools.builtin_tools["computer_use"].enabled = False

    assert plugin._seed_tool_config(agent_config) is False
    assert agent_config.tools.builtin_tools["computer_use"].enabled is False


def test_an_enabled_entry_is_not_rewritten():
    agent_config = _agent_config()
    plugin._seed_tool_config(agent_config)

    assert plugin._seed_tool_config(agent_config) is False
    assert agent_config.tools.builtin_tools["computer_use"].enabled is True
