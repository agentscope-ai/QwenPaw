# -*- coding: utf-8 -*-
"""Regression tests for structured tool failure outcomes."""

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolResponse
import pytest

from qwenpaw.agents.tools.ast_tool import ast_search
from qwenpaw.agents.tools.file_search import grep_search
from qwenpaw.agents.tools.lsp_tool import make_lsp_tool
from qwenpaw.agents.tools.run_tool_batch import (
    _json_tool_response,
    _response_payload,
)


@pytest.mark.asyncio
async def test_grep_missing_pattern_is_error():
    result = await grep_search("")

    assert result.state == ToolResultState.ERROR
    assert result.metadata["tool_outcome"]["code"] == "MISSING_PATTERN"
    assert "TOOL_OUTCOME:" in result.content[0].text


@pytest.mark.asyncio
async def test_grep_no_match_is_success(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("present", encoding="utf-8")

    result = await grep_search("absent", path=str(source))

    assert result.state == ToolResultState.SUCCESS
    assert "No matches found" in result.content[0].text


@pytest.mark.asyncio
async def test_ast_missing_pattern_is_error():
    result = await ast_search("", "python")

    assert result.state == ToolResultState.ERROR
    assert result.metadata["tool_outcome"]["code"] == "MISSING_PATTERN"


@pytest.mark.asyncio
async def test_lsp_unknown_operation_is_error():
    lsp = make_lsp_tool({})

    result = await lsp("unknown")

    assert result.state == ToolResultState.ERROR
    assert result.metadata["tool_outcome"]["code"] == "UNKNOWN_OPERATION"


def test_batch_prefers_tool_state_and_outcome_metadata():
    response = ToolResponse(
        content=[TextBlock(type="text", text="plain failure")],
        state=ToolResultState.ERROR,
        metadata={
            "tool_outcome": {
                "status": "error",
                "code": "TEST_FAILURE",
                "retryable": False,
                "same_args_retry_useful": False,
                "next_action": "change_input",
            },
        },
    )

    payload = _response_payload(response)

    assert payload["ok"] is False
    assert payload["state"] == "error"
    assert payload["outcome"]["code"] == "TEST_FAILURE"


def test_batch_json_error_response_has_error_state():
    response = _json_tool_response({"ok": False, "error": "invalid"})

    assert response.state == ToolResultState.ERROR
