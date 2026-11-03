# -*- coding: utf-8 -*-
"""Integration tests for the Codex harness adapter item mapping.

Covers src/qwenpaw/harnesses/codex/adapter.py (379 uncovered lines):
sandbox policy translation, skill formatting, notification turn-id
extraction, tool event name/argument/output mapping across all Codex
item types, and history item conversion.
"""

# pylint: disable=protected-access

from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_sandbox_policy_known_values() -> None:
    """Known sandbox policies map to Codex policy dicts."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert CodexAdapter._sandbox_policy("read-only") == {
        "type": "readOnly",
    }
    assert CodexAdapter._sandbox_policy("workspace-write") == {
        "type": "workspaceWrite",
    }
    assert CodexAdapter._sandbox_policy("danger-full-access") == {
        "type": "dangerFullAccess",
    }


@pytest.mark.integration
@pytest.mark.p1
def test_sandbox_policy_unknown_returns_none() -> None:
    """Unknown or empty policies return None."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert CodexAdapter._sandbox_policy("bogus") is None
    assert CodexAdapter._sandbox_policy("") is None
    assert CodexAdapter._sandbox_policy(None) is None


@pytest.mark.integration
@pytest.mark.p1
def test_format_skills_lists_names() -> None:
    """Skill groups render as a bullet list."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    result = {
        "data": [
            {"skills": [{"name": "alpha"}, {"name": "beta"}]},
            {"skills": [{"name": "gamma"}, {"other": "x"}]},
        ],
    }
    text = CodexAdapter._format_skills(result)
    assert "- alpha" in text
    assert "- beta" in text
    assert "- gamma" in text
    assert text.startswith("Codex skills:")


@pytest.mark.integration
@pytest.mark.p1
def test_format_skills_empty_message() -> None:
    """No skills yields the empty-availability message."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    text = CodexAdapter._format_skills({"data": []})
    assert "No Codex skills" in text
    assert CodexAdapter._format_skills(None) == text


@pytest.mark.integration
@pytest.mark.p1
def test_notification_turn_id_direct() -> None:
    """Direct turnId params win."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    message = {"params": {"turnId": "t-1"}}
    assert CodexAdapter._notification_turn_id(message) == "t-1"


@pytest.mark.integration
@pytest.mark.p1
def test_notification_turn_id_nested_turn() -> None:
    """Nested turn.id is the fallback."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    message = {"params": {"turn": {"id": "t-2"}}}
    assert CodexAdapter._notification_turn_id(message) == "t-2"


@pytest.mark.integration
@pytest.mark.p1
def test_notification_turn_id_missing() -> None:
    """Messages without turn identifiers return None."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert CodexAdapter._notification_turn_id({}) is None
    assert CodexAdapter._notification_turn_id({"params": {}}) is None


# ------------------------------------------------------------------ #
# tool name mapping
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_tool_name_command_execution() -> None:
    """commandExecution items map to the shell tool."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert CodexAdapter._tool_name({"type": "commandExecution"}) == "shell"


@pytest.mark.integration
@pytest.mark.p1
def test_tool_name_file_change() -> None:
    """fileChange items map to apply_patch."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert CodexAdapter._tool_name({"type": "fileChange"}) == "apply_patch"


@pytest.mark.integration
@pytest.mark.p1
def test_tool_name_mcp_dotted() -> None:
    """MCP tool calls build dotted server/namespace/tool names."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    item = {
        "type": "mcpToolCall",
        "server": "s1",
        "namespace": "ns",
        "tool": "t1",
    }
    assert CodexAdapter._tool_name(item) == "s1.ns.t1"


@pytest.mark.integration
@pytest.mark.p1
def test_tool_name_mcp_partial_parts() -> None:
    """Missing parts are dropped from the dotted name."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    item = {"type": "mcpToolCall", "server": "s1", "tool": "t1"}
    assert CodexAdapter._tool_name(item) == "s1.t1"
    assert CodexAdapter._tool_name({"type": "mcpToolCall"}) == "mcpToolCall"


@pytest.mark.integration
@pytest.mark.p1
def test_tool_name_collab_agent() -> None:
    """Collab agent calls use the agent.<tool> form."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    item = {"type": "collabAgentToolCall", "tool": "review"}
    assert CodexAdapter._tool_name(item) == "agent.review"
    assert (
        CodexAdapter._tool_name({"type": "collabAgentToolCall"})
        == "agent.collaborate"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_tool_name_web_and_image() -> None:
    """Web search and image items map to stable names."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert CodexAdapter._tool_name({"type": "webSearch"}) == "web_search"
    assert CodexAdapter._tool_name({"type": "imageView"}) == "view_image"
    assert (
        CodexAdapter._tool_name({"type": "imageGeneration"})
        == "image_generation"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_tool_name_unknown_passthrough() -> None:
    """Unknown item types pass through as the name."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert CodexAdapter._tool_name({"type": "customThing"}) == "customThing"
    assert CodexAdapter._tool_name({}) == "tool"


# ------------------------------------------------------------------ #
# tool arguments mapping
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_tool_arguments_command_execution() -> None:
    """Shell items expose command and cwd."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    item = {"type": "commandExecution", "command": "ls", "cwd": "/tmp"}
    args = CodexAdapter._tool_arguments(item)
    assert args == {"command": "ls", "cwd": "/tmp"}


@pytest.mark.integration
@pytest.mark.p1
def test_tool_arguments_file_change() -> None:
    """File changes expose path and kind per change."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    item = {
        "type": "fileChange",
        "changes": [
            {"path": "a.py", "kind": "modified"},
            "not-a-dict",
        ],
    }
    args = CodexAdapter._tool_arguments(item)
    assert args == {"changes": [{"path": "a.py", "kind": "modified"}]}


@pytest.mark.integration
@pytest.mark.p1
def test_tool_arguments_mcp_dict_passthrough() -> None:
    """Dict MCP arguments pass through; others are wrapped."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    item = {"type": "mcpToolCall", "arguments": {"k": 1}}
    assert CodexAdapter._tool_arguments(item) == {"k": 1}
    item2 = {"type": "mcpToolCall", "arguments": "raw"}
    assert CodexAdapter._tool_arguments(item2) == {"arguments": "raw"}


@pytest.mark.integration
@pytest.mark.p1
def test_tool_arguments_misc_types() -> None:
    """Web/image/collab items expose their key fields."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert CodexAdapter._tool_arguments(
        {"type": "webSearch", "query": "q"},
    ) == {"query": "q"}
    assert CodexAdapter._tool_arguments(
        {"type": "imageView", "path": "/x.png"},
    ) == {"path": "/x.png"}
    assert CodexAdapter._tool_arguments(
        {"type": "imageGeneration", "revisedPrompt": "p"},
    ) == {"prompt": "p"}
    assert CodexAdapter._tool_arguments({"type": "unknown"}) == {}


# ------------------------------------------------------------------ #
# tool output mapping
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_tool_output_command_execution() -> None:
    """Shell output comes from aggregatedOutput."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    item = {"type": "commandExecution", "aggregatedOutput": "ok"}
    assert CodexAdapter._tool_output(item) == "ok"
    assert CodexAdapter._tool_output({"type": "commandExecution"}) == ""


@pytest.mark.integration
@pytest.mark.p1
def test_tool_output_mcp_result_or_error() -> None:
    """MCP output prefers result, falls back to error."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    assert (
        CodexAdapter._tool_output(
            {"type": "mcpToolCall", "result": "done"},
        )
        == "done"
    )
    errored = CodexAdapter._tool_output(
        {"type": "mcpToolCall", "error": "boom"},
    )
    assert "boom" in errored


@pytest.mark.integration
@pytest.mark.p1
def test_tool_output_json_serializes_structured() -> None:
    """Structured outputs serialize to JSON text."""
    from qwenpaw.harnesses.codex.adapter import CodexAdapter

    out = CodexAdapter._tool_output(
        {"type": "imageView", "path": "/a.png"},
    )
    assert "/a.png" in out
    assert CodexAdapter._tool_output({"type": "unknown"}) == ""
