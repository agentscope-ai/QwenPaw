# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from agentscope.tool import Toolkit

from qwenpaw.governance.tool_registry import (
    ToolRegistry,
    _register_non_descriptor_tools,
)
from qwenpaw.runtime.builder import AgentBuilder


def test_personal_library_tools_are_wrapped_before_toolkit_registration(monkeypatch):
    async def search(query: str):
        return query

    async def read(document_id: str):
        return document_id

    wrapped: list[object] = []

    def wrap(tool, agent_id, request_context, governor):
        wrapped.append(tool)
        return object()

    monkeypatch.setattr(AgentBuilder, "_wrap_tool", staticmethod(wrap))
    builder = AgentBuilder.__new__(AgentBuilder)

    result = builder._wrap_personal_library_tools(
        [search, read],
        agent_id="default",
        request_context={"user_id": "user-1"},
        governor=None,
    )

    assert len(result) == 2
    assert wrapped == [search, read]


@pytest.mark.asyncio
async def test_wrapped_personal_library_tools_can_generate_tool_schemas():
    async def personal_library_search(query: str):
        """Search private documents."""
        return query

    builder = AgentBuilder.__new__(AgentBuilder)
    tools = builder._wrap_personal_library_tools(
        [personal_library_search],
        agent_id="default",
        request_context={"approval_level": "AUTO"},
        governor=None,
    )

    schemas = await Toolkit(tools=tools).get_tool_schemas()

    assert schemas[0]["function"]["name"] == "personal_library_search"


def test_personal_library_tools_are_registered_as_internal_governance_tools():
    registry = ToolRegistry()

    _register_non_descriptor_tools(registry)

    assert registry.python_to_policy_name("personal_library_search") == (
        "PersonalLibrarySearch"
    )
    assert registry.get_type("PersonalLibrarySearch") == "internal"
    assert registry.python_to_policy_name("personal_library_read") == (
        "PersonalLibraryRead"
    )
    assert registry.get_type("PersonalLibraryRead") == "internal"


def test_selected_personal_library_document_is_injected_as_read_only_context():
    class Context:
        def __init__(self):
            self.injections = []

        def inject_context(self, content, **metadata):
            self.injections.append((content, metadata))

    ctx = Context()
    AgentBuilder._inject_selected_personal_library_documents(
        ctx,
        {
            "personal_library_references": [
                {
                    "name": "AI写作需求文档.md",
                    "content": "唯一验收正文",
                    "truncated": False,
                },
            ],
        },
    )

    assert len(ctx.injections) == 1
    assert "AI写作需求文档.md" in ctx.injections[0][0]
    assert "唯一验收正文" in ctx.injections[0][0]
    assert "不要再到工作区搜索同名文件" in ctx.injections[0][0]
