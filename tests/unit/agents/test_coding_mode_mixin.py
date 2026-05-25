# -*- coding: utf-8 -*-
"""Tests for ``CodingModeMixin._build_sys_prompt`` rendering."""
# pylint: disable=protected-access
from __future__ import annotations

import pytest

from qwenpaw.agents.coding_mode_mixin import CodingModeMixin


class _FakeBaseAgent:
    """Stand-in for the ReActAgent base used in MRO."""

    def __init__(self) -> None:
        self._workspace_dir = "/tmp/workspace"
        self._agent_config: dict | None = None
        self.name: str | None = "test_agent"

    def _build_sys_prompt(self) -> str:
        return "BASE_PROMPT"


class _CodingAgent(CodingModeMixin, _FakeBaseAgent):
    """Concrete class mixing the coding mode behaviour into the fake base."""


@pytest.fixture(autouse=True)
def _no_disk_config(monkeypatch):
    """Force the in-memory config fallback by stubbing the disk loader."""

    def _raise(_agent_id):  # pragma: no cover - trivial stub
        raise FileNotFoundError("no on-disk config in tests")

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        _raise,
    )


def test_disabled_returns_base_prompt_unchanged() -> None:
    agent = _CodingAgent()
    agent._agent_config = {"coding_mode": {"enabled": False}}
    assert agent._build_sys_prompt() == "BASE_PROMPT"


def test_enabled_without_config_returns_base_prompt() -> None:
    agent = _CodingAgent()
    agent._agent_config = None
    assert agent._build_sys_prompt() == "BASE_PROMPT"


def test_enabled_appends_coding_block_with_project_dir() -> None:
    agent = _CodingAgent()
    agent._agent_config = {
        "coding_mode": {
            "enabled": True,
            "project_dir": "/home/user/repo",
        },
    }
    prompt = agent._build_sys_prompt()

    assert prompt.startswith("BASE_PROMPT")
    assert "## Coding Mode" in prompt
    assert "/home/user/repo" in prompt
    assert "/tmp/workspace" in prompt


def test_enabled_falls_back_to_workspace_when_no_project_dir() -> None:
    agent = _CodingAgent()
    agent._agent_config = {"coding_mode": {"enabled": True}}
    prompt = agent._build_sys_prompt()

    assert "Active project" in prompt
    # No project configured: project_dir should fall back to workspace
    assert prompt.count("/tmp/workspace") >= 2


def test_task_tracking_section_renders_slug_placeholder() -> None:
    agent = _CodingAgent()
    agent._agent_config = {
        "coding_mode": {
            "enabled": True,
            "project_dir": "/x",
        },
    }
    prompt = agent._build_sys_prompt()

    assert "### Task tracking" in prompt
    # The double-brace escapes must collapse to a single brace.
    assert "{SLUG}_TODO.md" in prompt
    assert "# {SLUG} —" in prompt
    # Critical: must mention .gitignore to keep notes out of git.
    assert ".gitignore" in prompt
    assert "*_TODO.md" in prompt


def test_code_reference_convention_section_present() -> None:
    agent = _CodingAgent()
    agent._agent_config = {
        "coding_mode": {"enabled": True, "project_dir": "/x"},
    }
    prompt = agent._build_sys_prompt()

    assert "### Code references" in prompt
    assert "`path/to/file.py:42`" in prompt
    assert "`:42-58`" in prompt


def test_tool_preference_section_mentions_lsp_and_ast_search() -> None:
    agent = _CodingAgent()
    agent._agent_config = {
        "coding_mode": {"enabled": True, "project_dir": "/x"},
    }
    prompt = agent._build_sys_prompt()

    assert "### Tool preference for code understanding" in prompt
    assert "`lsp`" in prompt
    assert "`ast_search`" in prompt
    assert "`grep_search`" in prompt
    assert "read-only" in prompt


def test_working_guidelines_updated() -> None:
    agent = _CodingAgent()
    agent._agent_config = {
        "coding_mode": {"enabled": True, "project_dir": "/x"},
    }
    prompt = agent._build_sys_prompt()

    # New rule must appear; old "Announce changes" must be gone.
    assert "Touch only what you must" in prompt
    assert "Announce changes" not in prompt
    assert "Read before you write" in prompt
    assert "Prefer targeted edits" in prompt
    assert "Summarise after each batch" in prompt


# ----------------------------------------------------------------------
# Tool registration hook
# ----------------------------------------------------------------------


class _FakeToolkit:
    """Minimal stand-in for ``agentscope.tool.Toolkit``."""

    def __init__(self) -> None:
        self.registered: list[str] = []

    def register_tool_function(
        self,
        func,
        namesake_strategy: str = "skip",
        async_execution: bool = False,
    ) -> None:
        del namesake_strategy, async_execution
        self.registered.append(getattr(func, "__name__", repr(func)))


def test_register_coding_mode_tools_skips_when_disabled(monkeypatch) -> None:
    agent = _CodingAgent()
    agent._agent_config = {"coding_mode": {"enabled": False}}
    toolkit = _FakeToolkit()

    # Even if both deps are available, disabled mode must register nothing.
    monkeypatch.setattr(
        "qwenpaw.agents.coding_mode_mixin.detect_available_lsp_languages",
        lambda _root: {"python": ["pylsp"]},
    )
    monkeypatch.setattr(
        "qwenpaw.agents.coding_mode_mixin.ast_tool.is_ast_grep_available",
        lambda: True,
    )

    agent._register_coding_mode_tools(toolkit)
    assert not toolkit.registered


def test_register_coding_mode_tools_registers_both(monkeypatch) -> None:
    agent = _CodingAgent()
    agent._agent_config = {
        "coding_mode": {"enabled": True, "project_dir": "/tmp/proj"},
    }
    toolkit = _FakeToolkit()

    monkeypatch.setattr(
        "qwenpaw.agents.coding_mode_mixin.detect_available_lsp_languages",
        lambda _root: {"python": ["pylsp"]},
    )
    monkeypatch.setattr(
        "qwenpaw.agents.coding_mode_mixin.ast_tool.is_ast_grep_available",
        lambda: True,
    )

    agent._register_coding_mode_tools(toolkit)

    assert "lsp" in toolkit.registered
    assert "ast_search" in toolkit.registered


def test_register_coding_mode_tools_omits_lsp_when_no_languages(
    monkeypatch,
) -> None:
    agent = _CodingAgent()
    agent._agent_config = {
        "coding_mode": {"enabled": True, "project_dir": "/tmp/proj"},
    }
    toolkit = _FakeToolkit()

    monkeypatch.setattr(
        "qwenpaw.agents.coding_mode_mixin.detect_available_lsp_languages",
        lambda _root: {},
    )
    monkeypatch.setattr(
        "qwenpaw.agents.coding_mode_mixin.ast_tool.is_ast_grep_available",
        lambda: True,
    )

    agent._register_coding_mode_tools(toolkit)

    assert "lsp" not in toolkit.registered
    assert "ast_search" in toolkit.registered


def test_register_coding_mode_tools_omits_ast_when_cli_missing(
    monkeypatch,
) -> None:
    agent = _CodingAgent()
    agent._agent_config = {
        "coding_mode": {"enabled": True, "project_dir": "/tmp/proj"},
    }
    toolkit = _FakeToolkit()

    monkeypatch.setattr(
        "qwenpaw.agents.coding_mode_mixin.detect_available_lsp_languages",
        lambda _root: {"python": ["pylsp"]},
    )
    monkeypatch.setattr(
        "qwenpaw.agents.coding_mode_mixin.ast_tool.is_ast_grep_available",
        lambda: False,
    )

    agent._register_coding_mode_tools(toolkit)

    assert "lsp" in toolkit.registered
    assert "ast_search" not in toolkit.registered
