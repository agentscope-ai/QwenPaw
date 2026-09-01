# -*- coding: utf-8 -*-
"""Integration tests for the Scroll context manager helpers.

Covers src/qwenpaw/agents/context/scroll/manager.py (546 uncovered
lines): compression trigger predicate, block metadata extraction,
bounded summary rendering, metadata pointer extraction, recall input
collection.
"""
# pylint: disable=protected-access

from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_should_compress_above_trigger() -> None:
    """Usage above the trigger compresses."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    assert ScrollContextManager.should_compress(101.0, 100.0) is True


@pytest.mark.integration
@pytest.mark.p1
def test_should_compress_at_trigger_stays_live() -> None:
    """Usage exactly at the trigger does not compress."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    assert ScrollContextManager.should_compress(100.0, 100.0) is False
    assert ScrollContextManager.should_compress(50.0, 100.0) is False


@pytest.mark.integration
@pytest.mark.p1
def test_block_metadata_dict_block() -> None:
    """Dict blocks expose their metadata dict."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    block = {"metadata": {"source": "tool"}}
    assert ScrollContextManager._block_metadata(block) == {"source": "tool"}


@pytest.mark.integration
@pytest.mark.p1
def test_block_metadata_object_block() -> None:
    """Object blocks expose a metadata attribute."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    class FakeBlock:
        metadata = {"kind": "thinking"}

    assert ScrollContextManager._block_metadata(FakeBlock()) == (
        {"kind": "thinking"}
    )


@pytest.mark.integration
@pytest.mark.p1
def test_block_metadata_invalid_type_yields_empty() -> None:
    """Non-dict metadata degrades to an empty dict."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    assert ScrollContextManager._block_metadata({"metadata": "junk"}) == {}
    assert ScrollContextManager._block_metadata({}) == {}


@pytest.mark.integration
@pytest.mark.p1
def test_bounded_summary_short_text() -> None:
    """Short text is whitespace-normalized and returned whole."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    result = ScrollContextManager._bounded_summary_text(
        "  hello   world  ",
        100,
    )
    assert result == "hello world"


@pytest.mark.integration
@pytest.mark.p1
def test_bounded_summary_truncates_middle() -> None:
    """Long text keeps head and tail with an omission marker."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    text = "x" * 500
    result = ScrollContextManager._bounded_summary_text(text, 100)
    assert len(result) <= 100
    assert "omitted" in result


@pytest.mark.integration
@pytest.mark.p1
def test_bounded_summary_zero_limit() -> None:
    """Zero or negative limits yield empty strings."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    assert ScrollContextManager._bounded_summary_text("abc", 0) == ""
    assert ScrollContextManager._bounded_summary_text("abc", -5) == ""


@pytest.mark.integration
@pytest.mark.p1
def test_summary_metadata_pointers_file_path() -> None:
    """file_path keys become [file:...] pointers."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    value = {"file_path": "/tmp/report.txt"}
    pointers = ScrollContextManager._summary_metadata_pointers(value)
    assert "[file:/tmp/report.txt]" in pointers


@pytest.mark.integration
@pytest.mark.p1
def test_summary_metadata_pointers_artifact_nested() -> None:
    """Nested artifact keys produce [artifact:...] pointers."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    value = {"nested": {"artifact_url": "http://x/a.png"}}
    pointers = ScrollContextManager._summary_metadata_pointers(value)
    assert any(p.startswith("[artifact:") for p in pointers)


@pytest.mark.integration
@pytest.mark.p1
def test_summary_metadata_pointers_dedup() -> None:
    """Duplicate pointers are deduplicated preserving order."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    value = {"path": "/a", "file_path": "/a"}
    pointers = ScrollContextManager._summary_metadata_pointers(value)
    assert pointers.count("[file:/a]") == 1


@pytest.mark.integration
@pytest.mark.p1
def test_summary_metadata_pointers_non_container() -> None:
    """Scalars and lists of scalars yield no pointers."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    assert not ScrollContextManager._summary_metadata_pointers(42)
    assert not ScrollContextManager._summary_metadata_pointers([1, 2])


@pytest.mark.integration
@pytest.mark.p1
def test_tool_call_inputs_collects_recall_calls() -> None:
    """recall_history tool calls are collected with parsed inputs."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    class Block:
        def __init__(self, type_, name, input_, id_):
            self.type = type_
            self.name = name
            self.input = input_
            self.id = id_

    class Msg:
        content = [
            Block("tool_call", "recall_history", '{"op": "search"}', "c1"),
            Block("tool_call", "shell", '{"cmd": "ls"}', "c2"),
        ]

    class State:
        context = [Msg()]

    class Agent:
        state = State()

    calls = ScrollContextManager._tool_call_inputs(Agent())
    assert "c1" in calls
    assert calls["c1"] == {"op": "search"}
    assert "c2" not in calls


@pytest.mark.integration
@pytest.mark.p1
def test_tool_call_inputs_json_string_fallback() -> None:
    """Invalid JSON string inputs degrade to empty dicts."""
    from qwenpaw.agents.context.scroll.manager import ScrollContextManager

    class Block:
        type = "tool_call"
        name = "recall_history"
        input = "not-json"
        id = "c1"

    class Msg:
        content = [Block()]

    class State:
        context = [Msg()]

    class Agent:
        state = State()

    calls = ScrollContextManager._tool_call_inputs(Agent())
    assert calls == {"c1": {}}
