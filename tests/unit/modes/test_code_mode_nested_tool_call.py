# -*- coding: utf-8 -*-
"""A tool called by another tool inside code mode reaches the catalog (#8903).

``CodeModeTool.execute_tool`` runs each script tool call in a one-tool
invocation toolkit. A tool that itself calls other tools through the current
toolkit, as ``run_tool_batch`` does, used to be routed into that one-tool
toolkit and failed with ``ToolNotFoundError``.
"""

import pytest
from agentscope.message import ToolCallBlock, ToolResultState
from agentscope.state import AgentState
from agentscope.tool import FunctionTool, Toolkit, ToolResponse

from qwenpaw.modes.coding.code_mode import (
    _execution_toolkit,
    build_code_mode_toolkit,
)


def get_current_time() -> ToolResponse:
    """Return a fixed time."""
    return ToolResponse(content=[{"type": "text", "text": "12:00"}])


def run_tool_batch() -> ToolResponse:
    """Stand-in for the batch tool that dispatches the nested calls."""
    return ToolResponse(content=[{"type": "text", "text": "batch"}])


async def _final(toolkit, name: str) -> ToolResponse:
    call = ToolCallBlock(id="call_1", name=name, input="{}")
    response = None
    async for chunk in toolkit.call_tool(call, AgentState()):
        if isinstance(chunk, ToolResponse):
            response = chunk
    assert response is not None
    return response


@pytest.mark.asyncio
async def test_a_nested_call_inside_an_invocation_reaches_the_catalog():
    toolkit = build_code_mode_toolkit(
        tools=[FunctionTool(get_current_time), FunctionTool(run_tool_batch)],
        skills_or_loaders=[],
    )
    batch = await toolkit.catalog.get_tool("run_tool_batch")
    token = _execution_toolkit.set(Toolkit(tools=[batch]))
    try:
        response = await _final(toolkit, "get_current_time")
    finally:
        _execution_toolkit.reset(token)

    assert response.state != ToolResultState.ERROR, response.content
    assert "12:00" in str(response.content)


@pytest.mark.asyncio
async def test_the_invoked_tool_itself_still_runs_in_its_invocation():
    toolkit = build_code_mode_toolkit(
        tools=[FunctionTool(get_current_time), FunctionTool(run_tool_batch)],
        skills_or_loaders=[],
    )
    batch = await toolkit.catalog.get_tool("run_tool_batch")
    token = _execution_toolkit.set(Toolkit(tools=[batch]))
    try:
        response = await _final(toolkit, "run_tool_batch")
    finally:
        _execution_toolkit.reset(token)

    assert "batch" in str(response.content)
