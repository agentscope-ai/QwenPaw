# -*- coding: utf-8 -*-
"""Tests for the AgentScope Driver tool adapter.

Covers _stringify, _blocks_from_mcp_content, _blocks_from_value,
_tool_chunk_from_driver_result, DriverCapabilityTool, and
build_driver_agent_tools, which previously sat at 0% coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import ToolResultState
from agentscope.permission import PermissionBehavior
from mcp.types import AudioContent, CallToolResult, ImageContent, TextContent

from qwenpaw.drivers.adapters import agentscope_tool as at
from qwenpaw.drivers.capabilities import (
    DriverCapability,
    DriverInvocationResult,
)


def _capability(name="cap", tool_name="", as_tool=True):
    exposure = SimpleNamespace(
        as_tool=as_tool,
        tool_name=tool_name,
        namespace="",
    )
    return DriverCapability(
        capability_id=f"id:{name}",
        driver_name="drv",
        protocol="mcp",
        kind="tool",
        action="call",
        name=name,
        description=f"desc {name}",
        input_schema={"type": "object"},
        exposure=exposure,
    )


def _convert(result: CallToolResult) -> dict:
    chunk = at._tool_chunk_from_driver_result(
        DriverInvocationResult(
            ok=True,
            value=result,
            metadata={"driver": "mcp"},
        ),
    )
    return chunk.model_dump(
        mode="json",
        exclude={
            "id": True,
            "content": {"__all__": {"id", "created_at", "finished_at"}},
        },
    )


# ---------------------------------------------------------------------------
# _stringify
# ---------------------------------------------------------------------------


class TestStringify:
    def test_none_empty(self):
        assert at._stringify(None) == ""

    def test_str_passthrough(self):
        assert at._stringify("hello") == "hello"

    def test_dict_json_dumped(self):
        result = at._stringify({"a": 1})
        assert '"a": 1' in result

    def test_model_dump_json_preferred(self):
        class Model:
            def model_dump_json(self, indent=None):
                return '{"from":"model"}'

        assert at._stringify(Model()) == '{"from":"model"}'

    def test_non_serializable_falls_back_to_str(self):
        class Weird:
            def __str__(self):
                return "weird-str"

        result = at._stringify(Weird())
        # json.dumps(default=str) serializes via __str__ into a JSON string
        assert "weird-str" in result


# ---------------------------------------------------------------------------
# _blocks_from_mcp_content
# ---------------------------------------------------------------------------


class TestBlocksFromMcpContent:
    def test_text_item(self):
        item = TextContent(type="text", text="hi")
        blocks = at._blocks_from_mcp_content([item])
        assert len(blocks) == 1
        assert blocks[0].text == "hi"

    def test_resource_text_item(self):
        resource = SimpleNamespace(text="resource body")
        item = SimpleNamespace(
            text=None,
            data=None,
            mime_type=None,
            resource=resource,
        )
        blocks = at._blocks_from_mcp_content([item])
        assert len(blocks) == 1
        assert blocks[0].text == "resource body"

    def test_resource_without_text_stringified(self):
        resource = SimpleNamespace(uri="file:///x")
        item = SimpleNamespace(
            text=None,
            data=None,
            mime_type=None,
            resource=resource,
        )
        blocks = at._blocks_from_mcp_content([item])
        assert len(blocks) == 1

    def test_unknown_item_stringified(self):
        item = SimpleNamespace()
        blocks = at._blocks_from_mcp_content([item])
        assert len(blocks) == 1

    def test_empty_content(self):
        assert at._blocks_from_mcp_content(None) == []
        assert at._blocks_from_mcp_content([]) == []


# ---------------------------------------------------------------------------
# _blocks_from_value
# ---------------------------------------------------------------------------


class TestBlocksFromValue:
    def test_plain_value_wrapped(self):
        blocks = at._blocks_from_value("raw result")
        assert len(blocks) == 1
        assert blocks[0].text == "raw result"

    def test_mcp_call_result_expanded(self):
        value = CallToolResult(
            content=[TextContent(type="text", text="x")],
        )
        blocks = at._blocks_from_value(value)
        assert [block.text for block in blocks] == ["x"]

    def test_mcp_empty_content_gives_placeholder(self):
        value = CallToolResult(content=[])
        blocks = at._blocks_from_value(value)
        assert [block.text for block in blocks] == [""]


# ---------------------------------------------------------------------------
# _tool_chunk_from_driver_result
# ---------------------------------------------------------------------------


class TestToolChunkFromDriverResult:
    @pytest.mark.parametrize("is_error", [False, True])
    @pytest.mark.parametrize(
        "structured",
        [{"ok": True}, [1, 2], "x", 0, False],
    )
    def test_sdk_result_preserves_text_structure_and_state(
        self,
        is_error,
        structured,
    ):
        result = CallToolResult.model_validate(
            {
                "content": [{"type": "text", "text": "summary"}],
                "isError": is_error,
                "structuredContent": structured,
            },
        )
        assert _convert(result) == {
            "content": [
                {"type": "text", "text": "summary"},
                {
                    "type": "text",
                    "text": structured
                    if isinstance(structured, str)
                    else json.dumps(structured, ensure_ascii=False, indent=2),
                },
            ],
            "state": "error" if is_error else "success",
            "is_last": True,
            "metadata": {"driver": "mcp"},
        }

    @pytest.mark.parametrize(
        ("content", "mime_type"),
        [
            (
                ImageContent(type="image", data="YWJj", mime_type="image/png"),
                "image/png",
            ),
            (
                AudioContent(type="audio", data="YWJj", mime_type="audio/wav"),
                "audio/wav",
            ),
        ],
    )
    def test_sdk_media_remains_a_data_block(self, content, mime_type):
        result = CallToolResult(content=[content])
        assert _convert(result) == {
            "content": [
                {
                    "type": "data",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": "YWJj",
                    },
                    "name": None,
                },
            ],
            "state": "success",
            "is_last": True,
            "metadata": {"driver": "mcp"},
        }

    def test_sdk_structured_only_result_is_not_wrapped_as_protocol_json(
        self,
    ):
        result = CallToolResult(content=[], structured_content=["item"])
        assert _convert(result)["content"] == [
            {"type": "text", "text": '[\n  "item"\n]'},
        ]

    def test_ok_success(self):
        result = DriverInvocationResult(ok=True, value="done")
        chunk = at._tool_chunk_from_driver_result(result)
        assert chunk.state == ToolResultState.SUCCESS
        assert chunk.is_last is True
        assert chunk.content[0].text == "done"

    def test_failure_result(self):
        result = DriverInvocationResult(
            ok=False,
            error_type="timeout",
            message="slow",
            metadata={"k": "v"},
        )
        chunk = at._tool_chunk_from_driver_result(result)
        assert chunk.state == ToolResultState.ERROR
        assert chunk.metadata == {"k": "v"}
        assert "timeout" in chunk.content[0].text
        assert "slow" in chunk.content[0].text

    def test_ok_metadata_copied(self):
        result = DriverInvocationResult(ok=True, value="x", metadata={"a": 1})
        chunk = at._tool_chunk_from_driver_result(result)
        assert chunk.metadata == {"a": 1}


# ---------------------------------------------------------------------------
# DriverCapabilityTool
# ---------------------------------------------------------------------------


class TestDriverCapabilityTool:
    def test_init_uses_tool_name_when_set(self):
        cap = _capability(tool_name="custom_tool")
        tool = at.DriverCapabilityTool(cap, AsyncMock())
        assert tool.name == "custom_tool"
        assert tool.description == "desc cap"

    def test_init_falls_back_to_capability_name(self):
        cap = _capability(tool_name="")
        tool = at.DriverCapabilityTool(cap, AsyncMock())
        assert tool.name == "cap"

    async def test_check_permissions_allows(self):
        cap = _capability()
        tool = at.DriverCapabilityTool(cap, AsyncMock())
        decision = await tool.check_permissions()
        assert decision.behavior == PermissionBehavior.ALLOW

    async def test_call_invokes_with_payload(self):
        cap = _capability(name="mycap")
        captured = {}

        async def invoker(invocation):
            captured["capability_id"] = invocation.capability_id
            captured["payload"] = invocation.payload
            captured["request_context"] = invocation.request_context
            return DriverInvocationResult(ok=True, value="done")

        tool = at.DriverCapabilityTool(
            cap,
            invoker,
            request_context={"agent_id": "a1"},
        )
        chunk = await tool(x=1)
        assert captured["capability_id"] == "id:mycap"
        assert captured["payload"] == {"x": 1}
        assert captured["request_context"] == {"agent_id": "a1"}
        assert chunk.content[0].text == "done"

    async def test_call_failure_propagates_error_chunk(self):
        cap = _capability()

        async def invoker(invocation):
            return DriverInvocationResult(
                ok=False,
                error_type="boom",
                message="failed",
            )

        tool = at.DriverCapabilityTool(cap, invoker)
        chunk = await tool()
        assert chunk.state == ToolResultState.ERROR


# ---------------------------------------------------------------------------
# build_driver_agent_tools
# ---------------------------------------------------------------------------


class TestBuildDriverAgentTools:
    async def test_none_manager_returns_empty(self):
        tools, hints = await at.build_driver_agent_tools(None, {})
        assert tools == []
        assert hints == []

    async def test_no_capabilities_returns_empty(self):
        manager = SimpleNamespace(
            list_capabilities=AsyncMock(return_value=[]),
            invoke_capability=AsyncMock(),
        )
        tools, hints = await at.build_driver_agent_tools(manager, {})
        assert tools == []
        assert hints == []

    async def test_tool_exposure_built_with_hint(self):
        manager = SimpleNamespace(
            list_capabilities=AsyncMock(
                return_value=[_capability(as_tool=True, tool_name="t1")],
            ),
            invoke_capability=AsyncMock(),
        )
        tools, hints = await at.build_driver_agent_tools(manager, {"a": "1"})
        assert len(tools) == 1
        assert tools[0].name == "t1"
        assert len(hints) == 1

    async def test_non_tool_exposure_filtered(self):
        manager = SimpleNamespace(
            list_capabilities=AsyncMock(
                return_value=[
                    _capability(as_tool=False, tool_name="hidden"),
                ],
            ),
            invoke_capability=AsyncMock(),
        )
        tools, hints = await at.build_driver_agent_tools(manager, {})
        assert tools == []
        assert hints == []

    async def test_capability_list_error_returns_empty(self):
        manager = SimpleNamespace(
            list_capabilities=AsyncMock(side_effect=RuntimeError("down")),
            invoke_capability=AsyncMock(),
        )
        tools, hints = await at.build_driver_agent_tools(manager, {})
        assert tools == []
        assert hints == []
