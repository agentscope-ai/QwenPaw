# -*- coding: utf-8 -*-
"""Isolate Code Mode execution context across spawned subagent turns (#8954)."""

from __future__ import annotations

from contextvars import ContextVar
import json

import pytest
from agentscope.message import TextBlock, ToolCallBlock, ToolResultState
from agentscope.permission import PermissionMode
from agentscope.state import AgentState
from agentscope.tool import FunctionTool, Toolkit, ToolChunk, ToolResponse

from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.config.context import current_script_tool_call
from qwenpaw.modes.coding.code_mode import (
    CodeModeToolkit,
    _execution_toolkit,
    build_code_mode_toolkit,
)


def _bypass_state() -> AgentState:
    state = AgentState()
    state.permission_context.mode = PermissionMode.BYPASS
    return state


def _bind_local_acting(toolkit: CodeModeToolkit, state: AgentState) -> None:
    toolkit.code.sandbox_config = lambda: None  # type: ignore[method-assign]
    toolkit.code.acting = lambda call: toolkit.call_tool(call, state)


async def _call_final(
    toolkit: Toolkit,
    name: str,
    arguments: dict | None = None,
    state: AgentState | None = None,
) -> ToolResponse:
    call = ToolCallBlock(
        id=f"call_{name}",
        name=name,
        input=json.dumps(arguments or {}, ensure_ascii=False),
    )
    final_response: ToolResponse | None = None
    async for chunk in toolkit.call_tool(call, state or _bypass_state()):
        if isinstance(chunk, ToolResponse):
            final_response = chunk
    assert final_response is not None
    return final_response


@pytest.mark.asyncio
async def test_in_process_subagent_spawned_via_task_tracker_runs_code():
    """Spawning a Code Mode child inside parent run_code must not leak state."""
    child_observations: dict[str, object] = {}

    def child_probe() -> ToolChunk:
        """Return a marker from the child's own tool catalog."""
        return ToolChunk(content=[TextBlock(text="CHILD-CATALOG-OK")])

    async def agent_tools_spawn(task: str) -> ToolChunk:
        """Simulate an in-process subagent submission through TaskTracker."""
        assert _execution_toolkit.get() is not None
        assert current_script_tool_call.get() is True

        tracker = TaskTracker(reconnect_grace_seconds=0)

        async def child_turn(_payload):
            child_observations["leaked_toolkit"] = _execution_toolkit.get()
            child_observations[
                "leaked_script_flag"
            ] = current_script_tool_call.get()
            child_state = _bypass_state()
            child_toolkit = build_code_mode_toolkit(
                tools=[FunctionTool(child_probe)],
                skills_or_loaders=[],
            )
            assert isinstance(child_toolkit, CodeModeToolkit)
            _bind_local_acting(child_toolkit, child_state)

            response = await _call_final(
                child_toolkit,
                "run_code",
                {"code": task},
                state=child_state,
            )
            child_observations["response"] = response
            yield (
                "data: "
                + json.dumps({"object": "response", "status": "completed"})
                + "\n\n"
            )

        queue, is_new = await tracker.attach_or_start(
            "sub-8d96d5f4",
            payload={"task": task},
            stream_fn=child_turn,
        )
        assert is_new is True
        async for _ in tracker.stream_from_queue(queue, "sub-8d96d5f4"):
            pass

        child_resp = child_observations["response"]
        assert isinstance(child_resp, ToolResponse)
        if child_resp.state == ToolResultState.ERROR:
            return ToolChunk(
                content=child_resp.content,
                state=ToolResultState.ERROR,
            )
        return ToolChunk(content=child_resp.content)

    def parent_probe() -> ToolChunk:
        """Verify parent script tool calls still work after child completes."""
        return ToolChunk(content=[TextBlock(text="PARENT-AFTER-OK")])

    parent_state = _bypass_state()
    parent_toolkit = build_code_mode_toolkit(
        tools=[FunctionTool(agent_tools_spawn), FunctionTool(parent_probe)],
        skills_or_loaders=[],
    )
    assert isinstance(parent_toolkit, CodeModeToolkit)
    _bind_local_acting(parent_toolkit, parent_state)

    parent_code = (
        "child = await tools.agent_tools_spawn("
        'task="r = await tools.child_probe(); '
        "text('PROBE-OK:' + r['content'][0]['text'])\")\n"
        "after = await tools.parent_probe()\n"
        "text(child['content'][0]['text'] + '|' + after['content'][0]['text'])"
    )
    parent_response = await _call_final(
        parent_toolkit,
        "run_code",
        {"code": parent_code},
        state=parent_state,
    )

    assert isinstance(child_observations.get("response"), ToolResponse)
    child_final = child_observations["response"]
    assert isinstance(child_final, ToolResponse)
    assert child_final.state != ToolResultState.ERROR, child_final.content
    assert (
        parent_response.state != ToolResultState.ERROR
    ), parent_response.content
    assert child_observations["leaked_toolkit"] is None
    assert child_observations["leaked_script_flag"] is False
    rendered = str(parent_response.content)
    assert "PROBE-OK:CHILD-CATALOG-OK|PARENT-AFTER-OK" in rendered


@pytest.mark.asyncio
async def test_child_toolkit_ignores_parent_invocation_even_in_same_task():
    """A distinct CodeModeToolkit must not route to another instance's slot."""

    def parent_shared() -> ToolResponse:
        """Parent copy of a tool sharing the same name."""
        return ToolResponse(content=[TextBlock(text="from-parent")])

    def child_shared() -> ToolResponse:
        """Child copy of a tool sharing the same name."""
        return ToolResponse(content=[TextBlock(text="from-child")])

    def view_image() -> ToolResponse:
        """Catalog tool only present on the child."""
        return ToolResponse(content=[TextBlock(text="image-ok")])

    # Align names before building toolkits so both expose ``shared_tool``.
    parent_tool = FunctionTool(parent_shared)
    parent_tool.name = "shared_tool"
    child_tool = FunctionTool(child_shared)
    child_tool.name = "shared_tool"

    child_state = _bypass_state()
    child_toolkit = build_code_mode_toolkit(
        tools=[child_tool, FunctionTool(view_image)],
        skills_or_loaders=[],
    )
    assert isinstance(child_toolkit, CodeModeToolkit)
    _bind_local_acting(child_toolkit, child_state)

    observed: dict[str, ToolResponse] = {}

    async def parent_acting(_call: ToolCallBlock):
        # Inline child calls in the exact coroutine where parent execute_tool
        # holds _execution_toolkit without TaskTracker boundaries.
        observed["run_code"] = await _call_final(
            child_toolkit,
            "run_code",
            {"code": "text('INLINE-CHILD-OK')"},
            state=child_state,
        )
        observed["same_name"] = await _call_final(
            child_toolkit,
            "shared_tool",
            state=child_state,
        )
        observed["catalog_other"] = await _call_final(
            child_toolkit,
            "view_image",
            state=child_state,
        )
        yield ToolResponse(content=[TextBlock(text="parent-done")])

    parent_state = _bypass_state()
    parent_toolkit = build_code_mode_toolkit(
        tools=[parent_tool],
        skills_or_loaders=[],
    )
    assert isinstance(parent_toolkit, CodeModeToolkit)
    parent_toolkit.code.acting = parent_acting

    call = ToolCallBlock(id="p1", name="shared_tool", input="{}")
    resp = await parent_toolkit.code.execute_tool(
        parent_tool,
        call,
        parent_state,
    )
    assert "parent-done" in str(resp.content)

    assert observed["run_code"].state != ToolResultState.ERROR, observed[
        "run_code"
    ].content
    assert "INLINE-CHILD-OK" in str(observed["run_code"].content)
    assert observed["same_name"].state != ToolResultState.ERROR, observed[
        "same_name"
    ].content
    assert "from-child" in str(observed["same_name"].content)
    assert observed["catalog_other"].state != ToolResultState.ERROR, observed[
        "catalog_other"
    ].content
    assert "image-ok" in str(observed["catalog_other"].content)


@pytest.mark.asyncio
async def test_unowned_invocation_routes_run_code_and_catalog_tools():
    """Manual _execution_toolkit injection resolves run_code and catalog."""

    def get_current_time() -> ToolResponse:
        """Return a fixed timestamp."""
        return ToolResponse(content=[TextBlock(text="12:00")])

    def run_tool_batch() -> ToolResponse:
        """Stand-in batch tool."""
        return ToolResponse(content=[TextBlock(text="batch-ok")])

    state = _bypass_state()
    toolkit = build_code_mode_toolkit(
        tools=[FunctionTool(get_current_time), FunctionTool(run_tool_batch)],
        skills_or_loaders=[],
    )
    assert isinstance(toolkit, CodeModeToolkit)
    _bind_local_acting(toolkit, state)

    batch = await toolkit.catalog.get_tool("run_tool_batch")
    token = _execution_toolkit.set(Toolkit(tools=[batch]))
    try:
        nested_catalog = await _call_final(
            toolkit,
            "get_current_time",
            state=state,
        )
        direct_batch = await _call_final(
            toolkit,
            "run_tool_batch",
            state=state,
        )
        code_resp = await _call_final(
            toolkit,
            "run_code",
            {"code": "text('FALLBACK-RUN-CODE-OK')"},
            state=state,
        )
    finally:
        _execution_toolkit.reset(token)

    assert (
        nested_catalog.state != ToolResultState.ERROR
    ), nested_catalog.content
    assert "12:00" in str(nested_catalog.content)
    assert "batch-ok" in str(direct_batch.content)
    assert code_resp.state != ToolResultState.ERROR, code_resp.content
    assert "FALLBACK-RUN-CODE-OK" in str(code_resp.content)


@pytest.mark.asyncio
async def test_task_tracker_clears_script_context_preserving_caller_vars():
    """TaskTracker resets transient script ContextVars but keeps caller ones."""
    caller_var: ContextVar[str] = ContextVar("caller_var", default="unset")
    seen: dict[str, object] = {}

    def dummy_tool() -> ToolResponse:
        """Dummy tool for temporary toolkit."""
        return ToolResponse(content=[TextBlock(text="ok")])

    caller_token = caller_var.set("cron-or-plugin-scope")
    exec_token = _execution_toolkit.set(
        Toolkit(tools=[FunctionTool(dummy_tool)]),
    )
    script_token = current_script_tool_call.set(True)
    try:
        tracker = TaskTracker(reconnect_grace_seconds=0)

        async def stream(_payload):
            seen["caller_var"] = caller_var.get()
            seen["exec_toolkit"] = _execution_toolkit.get()
            seen["script_call"] = current_script_tool_call.get()
            yield "data: done\n\n"

        queue, _ = await tracker.attach_or_start("run-ctx", None, stream)
        async for _ in tracker.stream_from_queue(queue, "run-ctx"):
            pass

        # Parent coroutine context must remain untouched.
        assert _execution_toolkit.get() is not None
        assert current_script_tool_call.get() is True
    finally:
        current_script_tool_call.reset(script_token)
        _execution_toolkit.reset(exec_token)
        caller_var.reset(caller_token)

    assert seen["caller_var"] == "cron-or-plugin-scope"
    assert seen["exec_toolkit"] is None
    assert seen["script_call"] is False
