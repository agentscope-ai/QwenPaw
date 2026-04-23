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

from qwenpaw.agents.utils.tool_message_utils import (
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
        assert result[0].content[0]["input"] == {"key": "value"}

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

    def test_returns_original_when_no_change(self):
        msgs = [_msg([_tool_use("id1")])]
        result = _repair_empty_tool_inputs(msgs)
        assert result is msgs


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

    def test_empty_messages_returns_empty(self):
        result = _sanitize_tool_messages([])
        assert result == []
