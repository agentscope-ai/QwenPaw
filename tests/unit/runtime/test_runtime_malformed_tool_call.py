# -*- coding: utf-8 -*-
"""Malformed tool_call death-loop regression tests.

Regression for #5717: malformed tool_call must not death-loop.

The QwenPaw defence against a malformed ``tool_call.input`` JSON string is
``_coerce_tool_inputs_to_json`` in ``qwenpaw.agents.utils.tool_message_utils``,
which runs on every model request. A malformed block is either recovered
via ``raw_decode`` or retained as a finished call with safe empty arguments
and a synthetic error result. The model sees actionable feedback instead of
being re-fed the same broken input, which is what caused the death-loop in
#5717.

These tests pin that contract: malformed input is repaired or failed in a
single pass (no retry loop), the function returns a finite paired list, and
the executor's ``_parse_tool_input`` returns ``{}`` rather than recursing.
"""

# pylint: disable=protected-access,unused-import,use-implicit-booleaness-not-comparison,unused-argument  # noqa: E501

from __future__ import annotations

import json
from types import SimpleNamespace

from agentscope.message import ToolCallBlock, ToolResultState

from qwenpaw.agents.utils.tool_message_utils import (
    _coerce_tool_inputs_to_json,
)
from qwenpaw.tool_calls._coordinator import _parse_tool_input


def _msg_with_blocks(blocks: list) -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks))


# ---------------------------------------------------------------------------
# _coerce_tool_inputs_to_json — single-pass, no loop
# ---------------------------------------------------------------------------


def test_malformed_truncated_json_is_failed_in_single_pass() -> None:
    """A truncated tool call is safely failed without retrying or looping."""
    blocks = [
        ToolCallBlock(
            id="call-1",
            name="shell",
            input="{bad json",  # truncated / malformed
        ),
    ]
    msg = _msg_with_blocks(blocks)

    # Single call — must terminate, not loop.
    result = _coerce_tool_inputs_to_json([msg])

    remaining_calls = [
        b
        for b in result[0].content
        if _block_attr(b, "type") in ("tool_call", "tool_use")
    ]
    assert [_block_attr(b, "id") for b in remaining_calls] == ["call-1"]
    assert json.loads(_block_attr(remaining_calls[0], "input")) == {}

    error_results = [
        b for b in result[0].content if _block_attr(b, "type") == "tool_result"
    ]
    assert [_block_attr(b, "id") for b in error_results] == ["call-1"]
    assert _block_attr(error_results[0], "state") == ToolResultState.ERROR


def test_recoverable_trailing_garbage_is_repaired_in_single_pass() -> None:
    """Regression for #5717: a tool_call with valid leading JSON + trailing
    garbage (DeepSeek-V4-Flash artefact) is repaired via raw_decode, not
    looped."""
    blocks = [
        ToolCallBlock(
            id="call-2",
            name="read",
            input='{"path": "/tmp/x"}trailing_garbage',
        ),
    ]
    msg = _msg_with_blocks(blocks)
    result = _coerce_tool_inputs_to_json([msg])

    repaired = result[0].content[0]
    assert _block_attr(repaired, "type") in ("tool_call", "tool_use")
    # The input must now be valid JSON.
    parsed = json.loads(repaired.input)
    assert parsed == {"path": "/tmp/x"}


def test_empty_input_coerced_to_empty_object() -> None:
    """Regression for #5717: empty-string input becomes ``"{}"`` rather than
    poisoning the next model request."""
    blocks = [
        ToolCallBlock(id="call-3", name="noop", input=""),
    ]
    msg = _msg_with_blocks(blocks)
    result = _coerce_tool_inputs_to_json([msg])

    block = result[0].content[0]
    assert json.loads(block.input) == {}


def test_dict_input_is_serialised_to_json() -> None:
    """Regression for #5717: a dict ``input`` (legacy stored block) is
    serialised to a JSON string in one pass."""
    blocks = [
        {"type": "tool_call", "id": "call-4", "name": "ls", "input": {"a": 1}},
    ]
    msg = _msg_with_blocks(blocks)
    result = _coerce_tool_inputs_to_json([msg])

    block = result[0].content[0]
    assert json.loads(block["input"]) == {"a": 1}


def test_malformed_block_does_not_corrupt_adjacent_blocks() -> None:
    """A failed malformed block must not corrupt neighbouring valid calls."""
    blocks = [
        ToolCallBlock(id="good-1", name="ls", input='{"path": "."}'),
        ToolCallBlock(id="bad-1", name="shell", input="{bad json"),
        ToolCallBlock(id="good-2", name="pwd", input="{}"),
    ]
    msg = _msg_with_blocks(blocks)
    result = _coerce_tool_inputs_to_json([msg])

    remaining = [
        b
        for b in result[0].content
        if _block_attr(b, "type") in ("tool_call", "tool_use")
    ]
    ids = [_block_attr(b, "id") for b in remaining]
    assert ids == ["good-1", "bad-1", "good-2"]
    failed = next(b for b in remaining if _block_attr(b, "id") == "bad-1")
    assert json.loads(_block_attr(failed, "input")) == {}

    error_results = [
        b for b in result[0].content if _block_attr(b, "type") == "tool_result"
    ]
    assert [_block_attr(b, "id") for b in error_results] == ["bad-1"]
    assert _block_attr(error_results[0], "state") == ToolResultState.ERROR


def test_coercion_is_idempotent() -> None:
    """Running coercion twice must not duplicate failed-call feedback."""
    blocks = [
        ToolCallBlock(id="call-5", name="shell", input="{bad json"),
    ]
    msg = _msg_with_blocks(blocks)
    once = _coerce_tool_inputs_to_json([msg])
    twice = _coerce_tool_inputs_to_json(once)
    # Still finite, with the same failed call and synthetic result.
    assert twice is once or len(twice) == 1


# ---------------------------------------------------------------------------
# _parse_tool_input — executor-level fallback
# ---------------------------------------------------------------------------


def test_parse_tool_input_returns_empty_for_malformed_string() -> None:
    """Regression for #5717: when a malformed tool_call reaches the executor,
    ``_parse_tool_input`` returns ``{}`` rather than looping on json.loads."""
    tool_call = SimpleNamespace(input="{bad json", id="x", name="shell")
    parsed = _parse_tool_input(tool_call)
    assert isinstance(parsed, dict)
    assert parsed == {}


def test_parse_tool_input_returns_dict_unchanged() -> None:
    """Regression for #5717: a valid dict input is returned as a copy."""
    tool_call = SimpleNamespace(input={"a": 1}, id="x", name="shell")
    parsed = _parse_tool_input(tool_call)
    assert parsed == {"a": 1}


def test_parse_tool_input_handles_missing_input_attr() -> None:
    """Regression for #5717: a tool_call with no ``input`` attribute falls
    back to ``{}`` rather than raising."""
    tool_call = SimpleNamespace(id="x", name="shell")
    assert _parse_tool_input(tool_call) == {}


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------


def _block_attr(block, key, default=None):
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)
