# -*- coding: utf-8 -*-
"""Unit tests for fuzzy JSON repair and error-feedback injection in
tool_message_utils.

These tests cover:
- _fuzzy_repair_json: five individual repair strategies + edge cases
- _repair_empty_tool_inputs: strict parse → fuzzy repair → error injection
"""

import importlib.util
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _load_module():
    """Load tool_message_utils without importing the full copaw package."""
    path = (
        Path(__file__).parent.parent
        / "src"
        / "copaw"
        / "agents"
        / "utils"
        / "tool_message_utils.py"
    )
    spec = importlib.util.spec_from_file_location("tool_message_utils", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()
_fuzzy_repair_json = _mod._fuzzy_repair_json
_repair_empty_tool_inputs = _mod._repair_empty_tool_inputs


class _Msg:
    """Minimal stand-in for AgentScope Msg."""

    def __init__(self, content):
        self.content = content


def _make_tool_use_msg(
    id_: str,
    name: str,
    input_: dict,
    raw_input: str = "",
) -> _Msg:
    return _Msg(
        [
            {
                "type": "tool_use",
                "id": id_,
                "name": name,
                "input": input_,
                "raw_input": raw_input,
            },
        ],
    )


# ---------------------------------------------------------------------------
# Tests for _fuzzy_repair_json
# ---------------------------------------------------------------------------


class TestFuzzyRepairJson:
    """Tests for the _fuzzy_repair_json helper."""

    def test_valid_json_passthrough(self):
        """Standard well-formed JSON is returned without modification."""
        result = _fuzzy_repair_json('{"command": "echo hello"}')
        assert result == {"command": "echo hello"}

    def test_single_quotes(self):
        """Single-quoted keys and values are repaired."""
        result = _fuzzy_repair_json("{'command': 'ls -la'}")
        assert result == {"command": "ls -la"}

    def test_unquoted_keys(self):
        """Bare identifier keys are wrapped in double quotes."""
        result = _fuzzy_repair_json('{command: "ls -la"}')
        assert result == {"command": "ls -la"}

    def test_trailing_comma(self):
        """Trailing commas before closing braces are removed."""
        result = _fuzzy_repair_json('{"command": "ls",}')
        assert result == {"command": "ls"}

    def test_trailing_comma_in_array(self):
        """Trailing commas in arrays are removed."""
        result = _fuzzy_repair_json('{"items": [1, 2, 3,]}')
        assert result == {"items": [1, 2, 3]}

    def test_bom_prefix(self):
        """A leading BOM character is stripped before parsing."""
        result = _fuzzy_repair_json("\ufeff" + '{"command": "ls"}')
        assert result == {"command": "ls"}

    def test_whitespace_only_surroundings(self):
        """Extra whitespace around the JSON is harmless."""
        result = _fuzzy_repair_json('   {"command": "ls"}   ')
        assert result == {"command": "ls"}

    def test_json_embedded_in_prose(self):
        """A JSON object embedded in surrounding text is extracted."""
        result = _fuzzy_repair_json(
            'Here is the tool call: {"command": "ls"} done',
        )
        assert result == {"command": "ls"}

    def test_totally_broken_returns_none(self):
        """Completely non-JSON input returns None."""
        result = _fuzzy_repair_json("this is not json at all")
        assert result is None

    def test_empty_string_returns_none(self):
        """An empty string returns None."""
        result = _fuzzy_repair_json("")
        assert result is None

    def test_whitespace_only_returns_none(self):
        """A whitespace-only string returns None."""
        result = _fuzzy_repair_json("   ")
        assert result is None

    def test_combined_single_quotes_and_trailing_comma(self):
        """Combined: single quotes + trailing comma are both repaired."""
        result = _fuzzy_repair_json("{'cmd': 'ls',}")
        assert result == {"cmd": "ls"}

    def test_multiple_keys(self):
        """Multiple keys with single quotes are all properly repaired."""
        result = _fuzzy_repair_json("{'key1': 'val1', 'key2': 'val2'}")
        assert result == {"key1": "val1", "key2": "val2"}

    def test_nested_json_extraction(self):
        """A nested JSON object with surrounding text is correctly extracted by brace balancing, not just regex."""
        result = _fuzzy_repair_json(
            'Here is the args: {"a": {"b": {"c": "d"}}} hope this works',
        )
        assert result == {"a": {"b": {"c": "d"}}}

    def test_pipeline_ordering_with_extraction(self):
        """Verifies that trailing commas and single quotes are repaired BEFORE extraction."""
        result = _fuzzy_repair_json(
            "Some text {'nested': {'b': 1,}, } more text.",
        )
        assert result == {"nested": {"b": 1}}


# ---------------------------------------------------------------------------
# Tests for _repair_empty_tool_inputs
# ---------------------------------------------------------------------------


class TestRepairEmptyToolInputs:
    """Tests for the three-stage repair pipeline."""

    # ---- Stage 1: strict JSON parse succeeds ----

    def test_strict_parse_success(self):
        """Valid JSON in raw_input is parsed and used as input."""
        msg = _make_tool_use_msg(
            "c1",
            "run_cmd",
            {},
            '{"command": "echo hello"}',
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {"command": "echo hello"}

    def test_no_change_when_input_already_set(self):
        """A block whose input is already populated is left unchanged."""
        msg = _make_tool_use_msg(
            "c1",
            "run_cmd",
            {"command": "ls"},
            '{"command": "echo"}',
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {"command": "ls"}

    def test_no_change_when_raw_input_empty(self):
        """A block with no raw_input is left unchanged."""
        msg = _make_tool_use_msg("c1", "run_cmd", {}, "")
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {}

    def test_no_change_when_raw_input_is_empty_object(self):
        """A raw_input of '{}' is treated as no-op (same as empty)."""
        msg = _make_tool_use_msg("c1", "run_cmd", {}, "{}")
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {}

    # ---- Stage 2: fuzzy repair rescues malformed JSON ----

    def test_fuzzy_repair_single_quotes(self):
        """Fuzzy repair handles single-quoted JSON."""
        msg = _make_tool_use_msg(
            "c2",
            "run_cmd",
            {},
            "{'command': 'ls -la'}",
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {"command": "ls -la"}

    def test_fuzzy_repair_trailing_comma(self):
        """Fuzzy repair handles trailing commas."""
        msg = _make_tool_use_msg(
            "c3",
            "run_cmd",
            {},
            '{"command": "ls",}',
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {"command": "ls"}

    def test_fuzzy_repair_unquoted_keys(self):
        """Fuzzy repair handles unquoted keys."""
        msg = _make_tool_use_msg(
            "c4",
            "run_cmd",
            {},
            '{command: "ls"}',
        )
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content[0]["input"] == {"command": "ls"}

    # ---- Stage 3: error feedback injection ----

    def test_error_feedback_injected_for_broken_json(self):
        """Completely unparseable raw_input triggers error feedback."""
        msg = _make_tool_use_msg(
            "c5",
            "run_cmd",
            {},
            "{totally broken json!!!}",
        )
        result = _repair_empty_tool_inputs([msg])
        block_input = result[0].content[0]["input"]
        assert block_input.get("_parse_error") is True
        assert "_error_message" in block_input
        assert "malformed JSON" in block_input["_error_message"]

    def test_error_message_contains_raw_input_preview(self):
        """The injected error message includes a preview of raw_input."""
        raw = "{bad json"
        msg = _make_tool_use_msg("c6", "run_cmd", {}, raw)
        result = _repair_empty_tool_inputs([msg])
        error_msg = result[0].content[0]["input"]["_error_message"]
        assert raw in error_msg

    def test_error_message_truncates_long_raw_input(self):
        """raw_input longer than 200 chars is truncated in the error message."""
        raw = "{" + "x" * 300  # 301-char malformed string
        msg = _make_tool_use_msg("c7", "run_cmd", {}, raw)
        result = _repair_empty_tool_inputs([msg])
        error_msg = result[0].content[0]["input"]["_error_message"]
        # preview should be truncated to 200+3 = 203 chars
        assert len(error_msg) < len(raw) + 500  # not storing the full raw

    # ---- Non-tool_use messages are untouched ----

    def test_non_tool_use_blocks_unchanged(self):
        """Text blocks within a message are left untouched."""
        msg = _Msg([{"type": "text", "text": "hello"}])
        original_content = list(msg.content)
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content == original_content

    def test_non_list_content_unchanged(self):
        """Messages with non-list content are left completely untouched."""
        msg = _Msg("plain string content")
        result = _repair_empty_tool_inputs([msg])
        assert result[0].content == "plain string content"

    def test_multiple_messages_mixed(self):
        """Mix of repairable and non-repairable messages in one batch."""
        msg_good = _make_tool_use_msg(
            "m1",
            "a",
            {},
            '{"x": 1}',
        )
        msg_fuzzy = _make_tool_use_msg(
            "m2",
            "b",
            {},
            "{'y': 2}",
        )
        msg_broken = _make_tool_use_msg(
            "m3",
            "c",
            {},
            "{totally broken}",
        )

        results = _repair_empty_tool_inputs([msg_good, msg_fuzzy, msg_broken])

        assert results[0].content[0]["input"] == {"x": 1}
        assert results[1].content[0]["input"] == {"y": 2}
        assert results[2].content[0]["input"].get("_parse_error") is True

    def test_returns_same_list_when_no_changes(self):
        """If no blocks need repair, the original list object is returned."""
        msg = _Msg([{"type": "text", "text": "no tools here"}])
        original = [msg]
        result = _repair_empty_tool_inputs(original)
        assert result is original
