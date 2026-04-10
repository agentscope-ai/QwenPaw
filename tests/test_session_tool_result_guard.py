"""Tests for oversized tool_result truncation in session persistence."""

import json
import pytest

from copaw.app.runner.session import (
    _compact_tool_results_in_state,
    _truncate_tool_result_output,
    _TOOL_RESULT_MAX_BYTES,
)


class TestTruncateToolResultOutput:
    """Tests for _truncate_tool_result_output."""

    def test_small_string_not_truncated(self):
        output = "small output"
        result = _truncate_tool_result_output(output, 1024, "test_tool")
        assert result == output

    def test_large_string_truncated(self):
        output = "A" * 200000
        result = _truncate_tool_result_output(output, 1024, "test_tool")
        assert "[auto-truncated]" in result
        assert "test_tool" in result
        assert len(result) < len(output)

    def test_small_list_not_truncated(self):
        output = [{"type": "text", "text": "small"}]
        original_text = output[0]["text"]
        _truncate_tool_result_output(output, 1024, "test_tool")
        assert output[0]["text"] == original_text

    def test_large_list_truncated(self):
        output = [{"type": "text", "text": "B" * 200000}]
        _truncate_tool_result_output(output, 1024, "wait_task")
        assert "[auto-truncated]" in output[0]["text"]
        assert "wait_task" in output[0]["text"]


class TestCompactToolResultsInState:
    """Tests for _compact_tool_results_in_state."""

    def _make_state(self, output_text: str, tool_name: str = "test_tool"):
        return {
            "agent": {
                "memory": {
                    "content": [
                        [
                            {
                                "role": "system",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "name": tool_name,
                                        "output": [
                                            {"type": "text", "text": output_text},
                                        ],
                                    },
                                ],
                            },
                            [],
                        ],
                    ],
                },
            },
        }

    def test_small_output_not_modified(self):
        state = self._make_state("small output")
        result = _compact_tool_results_in_state(state)
        text = result["agent"]["memory"]["content"][0][0]["content"][0]["output"][0]["text"]
        assert text == "small output"

    def test_large_output_truncated(self):
        state = self._make_state("X" * 200000, tool_name="wait_task")
        result = _compact_tool_results_in_state(state)
        text = result["agent"]["memory"]["content"][0][0]["content"][0]["output"][0]["text"]
        assert "[auto-truncated]" in text
        assert "wait_task" in text
        assert len(text) < 5000

    def test_string_output_truncated(self):
        state = {
            "agent": {
                "memory": {
                    "content": [
                        [
                            {
                                "role": "system",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "name": "execute_shell_command",
                                        "output": "Y" * 200000,
                                    },
                                ],
                            },
                            [],
                        ],
                    ],
                },
            },
        }
        result = _compact_tool_results_in_state(state)
        output = result["agent"]["memory"]["content"][0][0]["content"][0]["output"]
        assert "[auto-truncated]" in output
        assert "execute_shell_command" in output

    def test_no_agent_key(self):
        state = {"other": "data"}
        result = _compact_tool_results_in_state(state)
        assert result == state

    def test_no_memory_key(self):
        state = {"agent": {"other": "data"}}
        result = _compact_tool_results_in_state(state)
        assert result == state

    def test_no_content_key(self):
        state = {"agent": {"memory": {"other": "data"}}}
        result = _compact_tool_results_in_state(state)
        assert result == state

    def test_non_tool_result_not_modified(self):
        state = {
            "agent": {
                "memory": {
                    "content": [
                        [
                            {
                                "role": "assistant",
                                "content": [
                                    {"type": "text", "text": "Hello world"},
                                ],
                            },
                            [],
                        ],
                    ],
                },
            },
        }
        result = _compact_tool_results_in_state(state)
        text = result["agent"]["memory"]["content"][0][0]["content"][0]["text"]
        assert text == "Hello world"
