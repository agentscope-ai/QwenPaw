# -*- coding: utf-8 -*-
"""Tests for tool_message_utils — pure logic functions.

Covers:
- extract_tool_ids
- check_valid_messages
- _remove_invalid_tool_blocks
- _dedup_tool_blocks
- _repair_empty_tool_inputs
- _truncate_text
- _sanitize_tool_messages (orchestrator)
"""
# pylint: disable=redefined-outer-name
import json
from unittest.mock import MagicMock

from agentscope.message import (
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
)

from qwenpaw.agents.utils.tool_message_utils import (
    _coerce_tool_inputs_to_json,
    _dedup_tool_blocks,
    _remove_invalid_tool_blocks,
    _repair_empty_tool_inputs,
    _sanitize_tool_messages,
    _truncate_text,
    check_valid_messages,
    extract_tool_ids,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(content):
    """Build a minimal Msg-like mock with .content attribute."""
    m = MagicMock()
    m.content = content
    return m


def _tool_use(tid, name="my_tool"):
    return {"type": "tool_use", "id": tid, "name": name}


def _tool_result(tid):
    return {"type": "tool_result", "id": tid}


def _tool_result_blocks(msg):
    return [
        block
        for block in msg.content
        if isinstance(block, ToolResultBlock)
        or (isinstance(block, dict) and block.get("type") == "tool_result")
    ]


def _first_text(block):
    output = getattr(block, "output", [])
    first = output[0]
    if isinstance(first, TextBlock):
        return first.text
    return first["text"]


def _state_value(state):
    return getattr(state, "value", state)


# ---------------------------------------------------------------------------
# extract_tool_ids
# ---------------------------------------------------------------------------


class TestExtractToolIds:
    """P0: extract_tool_ids returns correct (use_ids, result_ids)."""

    def test_empty_content_returns_empty_sets(self):
        msg = _msg([])
        uses, results = extract_tool_ids(msg)
        assert uses == set()
        assert results == set()

    def test_string_content_returns_empty_sets(self):
        msg = _msg("plain text")
        uses, results = extract_tool_ids(msg)
        assert uses == set()
        assert results == set()

    def test_single_tool_use(self):
        msg = _msg([_tool_use("id1")])
        uses, results = extract_tool_ids(msg)
        assert uses == {"id1"}
        assert results == set()

    def test_single_tool_result(self):
        msg = _msg([_tool_result("id1")])
        uses, results = extract_tool_ids(msg)
        assert uses == set()
        assert results == {"id1"}

    def test_mixed_blocks(self):
        msg = _msg(
            [
                _tool_use("u1"),
                _tool_result("r1"),
                {"type": "text", "text": "hello"},
            ],
        )
        uses, results = extract_tool_ids(msg)
        assert uses == {"u1"}
        assert results == {"r1"}

    def test_block_without_id_ignored(self):
        msg = _msg([{"type": "tool_use", "name": "t"}])
        uses, results = extract_tool_ids(msg)
        assert uses == set()
        assert results == set()

    def test_non_dict_block_ignored(self):
        msg = _msg(["just a string", 42])
        uses, results = extract_tool_ids(msg)
        assert uses == set()
        assert results == set()


# ---------------------------------------------------------------------------
# check_valid_messages
# ---------------------------------------------------------------------------


class TestCheckValidMessages:
    """P0: check_valid_messages — use_ids must equal result_ids."""

    def test_empty_messages_is_valid(self):
        assert check_valid_messages([]) is True

    def test_no_tool_blocks_is_valid(self):
        msgs = [_msg("hello"), _msg("world")]
        assert check_valid_messages(msgs) is True

    def test_paired_use_and_result_is_valid(self):
        msgs = [
            _msg([_tool_use("id1")]),
            _msg([_tool_result("id1")]),
        ]
        assert check_valid_messages(msgs) is True

    def test_unpaired_use_is_invalid(self):
        msgs = [_msg([_tool_use("id1")])]
        assert check_valid_messages(msgs) is False

    def test_orphan_result_is_invalid(self):
        msgs = [_msg([_tool_result("id1")])]
        assert check_valid_messages(msgs) is False

    def test_multiple_pairs_valid(self):
        msgs = [
            _msg([_tool_use("a"), _tool_use("b")]),
            _msg([_tool_result("a")]),
            _msg([_tool_result("b")]),
        ]
        assert check_valid_messages(msgs) is True

    def test_partial_match_is_invalid(self):
        msgs = [
            _msg([_tool_use("a"), _tool_use("b")]),
            _msg([_tool_result("a")]),  # b never resolved
        ]
        assert check_valid_messages(msgs) is False


# ---------------------------------------------------------------------------
# _remove_invalid_tool_blocks
# ---------------------------------------------------------------------------


class TestRemoveInvalidToolBlocks:
    """P1: remove tool_use/tool_result with empty id or name."""

    def test_valid_blocks_unchanged(self):
        msg = _msg([_tool_use("id1"), _tool_result("id1")])
        result = _remove_invalid_tool_blocks([msg])
        assert result[0].content[0] == _tool_use("id1")

    def test_removes_tool_use_with_empty_id(self):
        msg = _msg([{"type": "tool_use", "id": "", "name": "t"}])
        result = _remove_invalid_tool_blocks([msg])
        assert result[0].content == []

    def test_removes_tool_use_with_none_id(self):
        msg = _msg([{"type": "tool_use", "id": None, "name": "t"}])
        result = _remove_invalid_tool_blocks([msg])
        assert result[0].content == []

    def test_removes_tool_use_with_empty_name(self):
        msg = _msg([{"type": "tool_use", "id": "id1", "name": ""}])
        result = _remove_invalid_tool_blocks([msg])
        assert result[0].content == []

    def test_removes_tool_result_with_empty_id(self):
        msg = _msg([{"type": "tool_result", "id": ""}])
        result = _remove_invalid_tool_blocks([msg])
        assert result[0].content == []

    def test_keeps_text_blocks_untouched(self):
        msg = _msg([{"type": "text", "text": "hello"}])
        result = _remove_invalid_tool_blocks([msg])
        assert result[0].content == [{"type": "text", "text": "hello"}]

    def test_non_list_content_unchanged(self):
        msg = _msg("plain text")
        result = _remove_invalid_tool_blocks([msg])
        assert result[0].content == "plain text"

    def test_returns_original_if_no_change(self):
        msgs = [_msg([_tool_use("id1")])]
        result = _remove_invalid_tool_blocks(msgs)
        assert result is msgs


# ---------------------------------------------------------------------------
# _dedup_tool_blocks
# ---------------------------------------------------------------------------


class TestDedupToolBlocks:
    """P1: remove duplicate tool_use blocks with same ID."""

    def test_no_duplicates_unchanged(self):
        msgs = [_msg([_tool_use("id1"), _tool_use("id2")])]
        result = _dedup_tool_blocks(msgs)
        assert result is msgs  # same object returned

    def test_removes_duplicate_tool_use(self):
        msg = _msg([_tool_use("id1"), _tool_use("id1")])
        result = _dedup_tool_blocks([msg])
        assert len(result[0].content) == 1
        assert result[0].content[0]["id"] == "id1"

    def test_keeps_non_tool_blocks(self):
        msg = _msg(
            [
                {"type": "text", "text": "hi"},
                _tool_use("id1"),
                _tool_use("id1"),
            ],
        )
        result = _dedup_tool_blocks([msg])
        types = [b["type"] for b in result[0].content]
        assert types == ["text", "tool_use"]

    def test_different_ids_both_kept(self):
        msg = _msg([_tool_use("id1"), _tool_use("id2")])
        result = _dedup_tool_blocks([msg])
        ids = [b["id"] for b in result[0].content]
        assert ids == ["id1", "id2"]


# ---------------------------------------------------------------------------
# _repair_empty_tool_inputs
# ---------------------------------------------------------------------------


class TestRepairEmptyToolInputs:
    """P1: repair tool_use with empty input but valid raw_input."""

    def test_repairs_empty_input_from_raw_input(self):
        raw = json.dumps({"key": "value"})
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": {},
                    "raw_input": raw,
                },
            ],
        )
        result = _repair_empty_tool_inputs([msg])
        # _repair_empty_tool_inputs now stores the repaired value as a JSON
        # string (consistent with ToolCallBlock.input being str) rather than
        # the parsed dict, so downstream formatters receive valid JSON.
        assert result[0].content[0]["input"] == json.dumps({"key": "value"})

    def test_skips_repair_when_input_already_set(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": {"existing": True},
                    "raw_input": '{"other": 1}',
                },
            ],
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {"existing": True}

    def test_skips_repair_when_raw_input_empty(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": {},
                    "raw_input": "",
                },
            ],
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {}

    def test_skips_repair_when_raw_input_is_empty_json(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": {},
                    "raw_input": "{}",
                },
            ],
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {}

    def test_handles_invalid_json_gracefully(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": {},
                    "raw_input": "not valid json",
                },
            ],
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {}

    def test_recovers_raw_input_with_trailing_garbage(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": {},
                    "raw_input": '{"key": "value"}trailing garbage',
                },
            ],
        )
        result = _repair_empty_tool_inputs([msg])
        assert json.loads(result[0].content[0]["input"]) == {"key": "value"}

    def test_recovers_raw_input_with_leading_whitespace_and_trailing_garbage(
        self,
    ):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": {},
                    "raw_input": '\n  {"path": "README.md"}trailing garbage',
                },
            ],
        )
        result = _repair_empty_tool_inputs([msg])
        assert json.loads(result[0].content[0]["input"]) == {
            "path": "README.md",
        }

    def test_non_dict_raw_decode_does_not_repair(self):
        """raw_decode recovering a non-dict should not overwrite input."""
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": {},
                    "raw_input": "42trailing",
                },
            ],
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {}

    def test_returns_original_when_no_change(self):
        msgs = [_msg([_tool_use("id1")])]
        result = _repair_empty_tool_inputs(msgs)
        assert result is msgs


# ---------------------------------------------------------------------------
# _coerce_tool_inputs_to_json — raw_decode recovery
# ---------------------------------------------------------------------------


class TestCoerceToolInputsRawDecode:
    """raw_decode recovery for no-param tool calls with trailing garbage."""

    def test_valid_json_unchanged(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": '{"x": 1}',
                },
            ],
        )
        result = _coerce_tool_inputs_to_json([msg])
        assert result[0].content[0]["input"] == '{"x": 1}'

    def test_empty_braces_with_trailing_garbage_recovered(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": "{}some trailing junk",
                },
            ],
        )
        result = _coerce_tool_inputs_to_json([msg])
        assert len(result[0].content) == 1
        assert json.loads(result[0].content[0]["input"]) == {}

    def test_object_with_trailing_garbage_recovered(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": '{"key": "val"}extra',
                },
            ],
        )
        result = _coerce_tool_inputs_to_json([msg])
        assert len(result[0].content) == 1
        assert json.loads(result[0].content[0]["input"]) == {"key": "val"}

    def test_object_with_leading_whitespace_and_trailing_garbage_recovered(
        self,
    ):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": '\n  {"path": "README.md"}extra',
                },
            ],
        )
        result = _coerce_tool_inputs_to_json([msg])
        assert len(result[0].content) == 1
        assert json.loads(result[0].content[0]["input"]) == {
            "path": "README.md",
        }

    def test_completely_invalid_json_drops_block(self):
        msg = _msg(
            [
                {
                    "type": "tool_use",
                    "id": "id1",
                    "name": "t",
                    "input": "totally not json at all",
                },
            ],
        )
        result = _coerce_tool_inputs_to_json([msg])
        assert result[0].content[0]["input"] == "{}"
        assert result[0].content[0]["state"] == "finished"
        results = _tool_result_blocks(result[0])
        assert len(results) == 1
        assert isinstance(results[0], ToolResultBlock)
        assert results[0].id == "id1"
        assert _state_value(results[0].state) == ToolResultState.ERROR.value
        text = _first_text(results[0])
        assert "Tool call `t` was not executed" in text
        assert "valid JSON arguments" in text
        assert "tool_call_id" not in text
        assert "id1" not in text
        assert "totally not json" not in text

    def test_pydantic_block_invalid_json_becomes_error_tool_result(self):
        msg = _msg(
            [
                ToolCallBlock(
                    type="tool_call",
                    id="id1",
                    name="t",
                    input="not json",
                ),
            ],
        )

        result = _coerce_tool_inputs_to_json([msg])

        call = result[0].content[0]
        assert isinstance(call, ToolCallBlock)
        assert call.input == "{}"
        assert _state_value(call.state) == ToolCallState.FINISHED.value
        results = _tool_result_blocks(result[0])
        assert len(results) == 1
        assert isinstance(results[0], ToolResultBlock)
        assert results[0].id == "id1"
        assert _state_value(results[0].state) == ToolResultState.ERROR.value

    def test_non_dict_recovered_value_becomes_error_tool_result(self):
        """raw_decode recovering a non-dict should not create a tool call."""
        for bad_input in ["42trailing", '"hello"garbage', "[1,2,3]extra"]:
            msg = _msg(
                [
                    {
                        "type": "tool_use",
                        "id": "id1",
                        "name": "t",
                        "input": bad_input,
                    },
                ],
            )
            result = _coerce_tool_inputs_to_json([msg])
            results = _tool_result_blocks(result[0])
            assert len(results) == 1
            text = _first_text(results[0])
            assert "Tool call `t` was not executed" in text
            assert bad_input not in text


# ---------------------------------------------------------------------------
# _truncate_text
# ---------------------------------------------------------------------------


class TestTruncateText:
    """P1: _truncate_text keeps head + tail, inserts marker."""

    def test_short_text_unchanged(self):
        text = "hello"
        assert _truncate_text(text, 100) == "hello"

    def test_exact_length_unchanged(self):
        text = "a" * 50
        assert _truncate_text(text, 50) == text

    def test_long_text_contains_truncation_marker(self):
        text = "a" * 200
        result = _truncate_text(text, 100)
        assert "truncated" in result

    def test_long_text_preserves_head_and_tail(self):
        text = "HEAD" + "x" * 200 + "TAIL"
        result = _truncate_text(text, 20)
        assert result.startswith("HEAD")
        assert result.endswith("TAIL")

    def test_empty_string_returns_empty(self):
        assert _truncate_text("", 100) == ""

    def test_none_coerced_to_empty(self):
        assert _truncate_text(None, 100) == ""

    def test_result_shorter_than_original(self):
        text = "x" * 1000
        result = _truncate_text(text, 100)
        assert len(result) < len(text)


# ---------------------------------------------------------------------------
# _sanitize_tool_messages (orchestrator)
# ---------------------------------------------------------------------------


class TestSanitizeToolMessages:
    """P1: _sanitize_tool_messages fixes ordering and pairing."""

    def test_valid_messages_unchanged(self):
        msgs = [
            _msg([_tool_use("id1")]),
            _msg([_tool_result("id1")]),
        ]
        result = _sanitize_tool_messages(msgs)
        # Valid messages should be returned (possibly same object)
        uses = set()
        results = set()
        for m in result:
            u, r = extract_tool_ids(m)
            uses |= u
            results |= r
        assert uses == results

    def test_removes_unpaired_tool_use(self):
        msgs = [
            _msg([_tool_use("id1")]),
            _msg("regular message"),
        ]
        result = _sanitize_tool_messages(msgs)
        for m in result:
            u, _ = extract_tool_ids(m)
            assert "id1" not in u

    def test_malformed_tool_call_pair_becomes_error_tool_result(self):
        msgs = [
            _msg(
                [
                    {
                        "type": "tool_call",
                        "id": "call_bad_json",
                        "name": "write_file",
                        "input": (
                            '{"file_path": "/tmp/out.py", '
                            '"content": "unterminated'
                        ),
                    },
                ],
            ),
            _msg([_tool_result("call_bad_json")]),
        ]

        result = _sanitize_tool_messages(msgs)

        assert len(result) == 1
        assert result[0].content[0]["input"] == "{}"
        assert result[0].content[0]["state"] == "finished"
        results = _tool_result_blocks(result[0])
        assert len(results) == 1
        assert results[0].id == "call_bad_json"
        text = _first_text(results[0])
        assert "Tool call `write_file` was not executed" in text
        assert "tool_call_id" not in text
        assert "call_bad_json" not in text
        uses, results = extract_tool_ids(result[0])
        assert uses == {"call_bad_json"}
        assert results == {"call_bad_json"}

    def test_empty_messages_returns_empty(self):
        result = _sanitize_tool_messages([])
        assert result == []

    def test_self_paired_message_kept_when_another_block_unpaired(self):
        # An AgentScope 2.0 self-paired assistant message carries its own
        # tool_use and matching tool_result (plus text). When an *unrelated*
        # unpaired tool_use elsewhere triggers sanitation, the valid
        # self-paired turn must NOT be dropped (previously it was silently
        # removed, losing the text and leaving an unpaired tool_use).
        self_paired = _msg(
            [
                {"type": "text", "text": "keep me"},
                _tool_use("paired"),
                _tool_result("paired"),
            ],
        )
        msgs = [
            _msg([_tool_use("orphan")]),  # unpaired -> triggers sanitation
            self_paired,
            _msg("regular message"),
        ]

        result = _sanitize_tool_messages(msgs)

        assert self_paired in result, "self-paired message must be preserved"
        # The unpaired orphan tool_use is still removed.
        remaining_uses: set = set()
        for m in result:
            u, _ = extract_tool_ids(m)
            remaining_uses |= u
        assert "orphan" not in remaining_uses
        assert "paired" in remaining_uses
