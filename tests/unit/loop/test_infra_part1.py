# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Unit tests for Checklist Part 1: infra items 4, 6B, 7C."""
from __future__ import annotations

from unittest.mock import MagicMock


# ── 改动4: dynamic command broadcasting ──


class _FakeSpec:
    """Minimal CommandSpec stand-in."""

    def __init__(self, name, help_text=""):
        self.name = name
        self.help_text = help_text
        self.category = "plugin"


class _FakeRegistry:
    """Minimal SlashCommandRegistry stand-in."""

    def __init__(self, specs: dict[str, _FakeSpec]):
        self._specs = specs

    def names(self) -> list[str]:
        return sorted(self._specs.keys())

    def resolve(self, raw_text: str):
        name = raw_text.lstrip("/").split()[0]
        spec = self._specs.get(name)
        if spec:
            return (spec, "")
        return None


class _FakePlugins:
    def __init__(self, registry):
        self.slash_command_registry = registry


class _FakeWorkspace:
    def __init__(self, registry):
        self.plugins = _FakePlugins(registry)


class TestDynamicCommands:
    """改动4: ACP _build_available_commands() reads workspace."""

    def test_static_only(self):
        """Without workspace, returns static commands."""
        from qwenpaw.agents.acp.server import (
            QwenPawACPAgent,
        )

        server = object.__new__(QwenPawACPAgent)
        server._workspace = None
        cmds = server._build_available_commands()
        names = [c.name for c in cmds]
        assert "clear" in names
        assert "compact" in names

    def test_with_plugin_commands(self):
        """Plugin-registered commands appear in results."""
        from qwenpaw.agents.acp.server import (
            QwenPawACPAgent,
        )

        registry = _FakeRegistry(
            {
                "ralph": _FakeSpec("ralph", "Story loop"),
                "ultrawork": _FakeSpec(
                    "ultrawork",
                    "Todo loop",
                ),
            },
        )
        server = object.__new__(QwenPawACPAgent)
        server._workspace = _FakeWorkspace(registry)
        cmds = server._build_available_commands()
        names = [c.name for c in cmds]
        assert "ralph" in names
        assert "ultrawork" in names
        for c in cmds:
            if c.name == "ralph":
                assert c.description == "Story loop"

    def test_no_duplicates(self):
        """Static commands are not duplicated by registry."""
        from qwenpaw.agents.acp.server import (
            QwenPawACPAgent,
        )

        registry = _FakeRegistry(
            {"clear": _FakeSpec("clear", "Clear chat")},
        )
        server = object.__new__(QwenPawACPAgent)
        server._workspace = _FakeWorkspace(registry)
        cmds = server._build_available_commands()
        clear_count = sum(1 for c in cmds if c.name == "clear")
        assert clear_count == 1


# ── 改动6B: context injection ──


class TestContextInjection:
    """改动6B: HookContext.inject_context + Runtime assembly."""

    def test_inject_adds_to_list(self):
        """inject_context() appends to context_injections."""
        from qwenpaw.runtime.hooks import HookContext

        ctx = HookContext(
            request=MagicMock(),
            session_id="s1",
            agent_id="a1",
            root_session_id="s1",
            root_agent_id="a1",
            workspace_dir=None,
            workspace=MagicMock(),
            app_services=MagicMock(),
        )
        ctx.inject_context("Budget: 5/15", priority=10, source="goal")
        ctx.inject_context("Keep going", priority=50, source="loop")
        assert len(ctx.context_injections) == 2
        assert ctx.context_injections[0]["priority"] == 10
        assert ctx.context_injections[1]["content"] == "Keep going"

    def test_runtime_apply_sorts_by_priority(self):
        """_apply_context_injections sorts by priority."""
        from qwenpaw.runtime.hooks import HookContext
        from qwenpaw.runtime.runtime import Runtime

        ctx = HookContext(
            request=MagicMock(),
            session_id="s1",
            agent_id="a1",
            root_session_id="s1",
            root_agent_id="a1",
            workspace_dir=None,
            workspace=MagicMock(),
            app_services=MagicMock(),
        )
        ctx.inject_context("Second", priority=50)
        ctx.inject_context("First", priority=10)
        ctx.input_msgs = []

        Runtime._apply_context_injections(ctx)

        assert len(ctx.input_msgs) == 1
        blocks = ctx.input_msgs[0].content
        assert isinstance(blocks, list)
        text = blocks[0].text
        assert text.startswith("First")
        assert "Second" in text

    def test_no_injection_no_msg(self):
        """Empty context_injections => no message added."""
        from qwenpaw.runtime.hooks import HookContext
        from qwenpaw.runtime.runtime import Runtime

        ctx = HookContext(
            request=MagicMock(),
            session_id="s1",
            agent_id="a1",
            root_session_id="s1",
            root_agent_id="a1",
            workspace_dir=None,
            workspace=MagicMock(),
            app_services=MagicMock(),
        )
        ctx.input_msgs = []
        Runtime._apply_context_injections(ctx)
        assert len(ctx.input_msgs) == 0
